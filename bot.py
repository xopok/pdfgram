"""
Main Telegram bot module for pdfgram.
Handles messages, arXiv parsing, PDF margin cropping, and returning cropped documents.
"""

import os
import re
import logging
import tempfile

from telegram import Update
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import Config
from cropper import download_file, crop_pdf, read_pdf_title
from arxiv_utils import extract_arxiv_id, get_arxiv_pdf_url, fetch_arxiv_metadata, make_arxiv_filename

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# Suppress noisy HTTP keep-alive pings from httpx and httpcore
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("pdfgram")


def is_authorized(user_id: int, config: Config) -> bool:
    """Checks whether a Telegram user ID is authorized."""
    if not config.allowed_user_ids:
        return True
    return user_id in config.allowed_user_ids


async def auth_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if the user is authorized, otherwise replies with an error."""
    config: Config = context.bot_data["config"]
    user = update.effective_user
    if not user:
        return False
    if not is_authorized(user.id, config):
        logger.warning(f"Unauthorized access attempt by user {user.id} (@{user.username})")
        if update.message:
            await update.message.reply_text("⛔ Access denied: You are not authorized to use this bot.")
        return False
    return True


async def command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start and /help commands."""
    if not await auth_check(update, context):
        return

    user = update.effective_user
    logger.info(f"User {user.id} (@{user.username}) invoked /start or /help")

    msg = (
        "👋 *Welcome to pdfgram!*\n\n"
        "Send me a link to an **arXiv paper** or any **PDF file**, and I will:\n"
        "1. Download the document\n"
        "2. Automatically crop the margins using `pdfCropMargins`\n"
        "3. Rename arXiv papers with their ID and paper title\n"
        "4. Send the cropped document right back to you here!\n\n"
        "📚 *Usage:*\n"
        "• Send an arXiv link: `https://arxiv.org/abs/2609.19101` (or `/pdf/`)\n"
        "• Send any PDF link: `https://example.com/paper.pdf`\n"
        "• Or directly upload a PDF document into the chat\n\n"
        "⚙️ *Commands:*\n"
        "• `/status` — View current crop settings\n"
        "• `/help` — Show this message"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def command_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /status command."""
    if not await auth_check(update, context):
        return

    config: Config = context.bot_data["config"]
    user = update.effective_user
    logger.info(f"User {user.id} (@{user.username}) invoked /status")

    msg = (
        "⚙️ *pdfgram Bot Settings*\n\n"
        f"• *Crop Margin Retain:* `{config.crop_percent}%`\n"
        f"• *Uniform Cropping:* `{'Enabled' if config.crop_uniform else 'Disabled'}`\n"
        f"• *Same Page Size:* `{'Enabled' if config.crop_same_page_size else 'Disabled'}`\n"
        f"• *Max Download Size:* `{config.max_file_size_mb} MB`\n"
        f"• *Access Whitelist:* `{'Active (' + str(len(config.allowed_user_ids)) + ' users)' if config.allowed_user_ids else 'Open (no whitelist)'}`\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def process_pdf_job(
    target_url: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Core workflow for fetching, cropping, and returning a PDF."""
    config: Config = context.bot_data["config"]
    user = update.effective_user
    chat_id = update.effective_chat.id

    logger.info(f"Processing PDF request from user {user.id} (@{user.username}): {target_url}")

    # Step 1: Detect arXiv vs generic PDF
    arxiv_id = extract_arxiv_id(target_url)
    arxiv_title = None
    download_url = target_url

    status_msg = await update.message.reply_text("🔍 *Analyzing link...*", parse_mode=ParseMode.MARKDOWN)

    if arxiv_id:
        download_url = get_arxiv_pdf_url(arxiv_id)
        logger.info(f"Identified arXiv paper: {arxiv_id}, resolved download URL: {download_url}")
        await status_msg.edit_text(f"📄 *Detected arXiv paper:* `{arxiv_id}`\n⏳ Fetching metadata...", parse_mode=ParseMode.MARKDOWN)
        arxiv_title, _ = await fetch_arxiv_metadata(arxiv_id)
        if arxiv_title:
            logger.info(f"ArXiv title for {arxiv_id}: {arxiv_title!r}")
            await status_msg.edit_text(
                f"📄 *arXiv:* `{arxiv_id}`\n📌 *Title:* {arxiv_title}\n⏳ Downloading PDF document...",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            logger.info(f"Could not fetch metadata for {arxiv_id}, continuing with ID only.")
            await status_msg.edit_text(f"📄 *arXiv:* `{arxiv_id}`\n⏳ Downloading PDF document...", parse_mode=ParseMode.MARKDOWN)
    else:
        logger.info(f"Treating as standard PDF URL: {target_url}")
        await status_msg.edit_text("📄 *PDF link detected.*\n⏳ Downloading document...", parse_mode=ParseMode.MARKDOWN)

    # Step 2: Download PDF to temporary directory
    with tempfile.TemporaryDirectory() as tmp_dir:
        input_pdf_path = os.path.join(tmp_dir, "input.pdf")
        cropped_pdf_path = os.path.join(tmp_dir, "cropped.pdf")

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)

        ok, error_msg, suggested_fname = await download_file(
            url=download_url,
            destination_path=input_pdf_path,
            max_size_mb=config.max_file_size_mb,
        )

        if not ok:
            logger.error(f"Download failed for {download_url}: {error_msg}")
            await status_msg.edit_text(f"❌ *Download failed:*\n{error_msg}", parse_mode=ParseMode.MARKDOWN)
            return

        # Determine target filename
        if arxiv_id:
            final_filename = make_arxiv_filename(arxiv_id, arxiv_title)
            document_title = arxiv_title or arxiv_id
        else:
            pdf_title = read_pdf_title(input_pdf_path)
            document_title = pdf_title or suggested_fname or "document"
            if pdf_title:
                final_filename = f"{pdf_title}.pdf"
            elif suggested_fname:
                final_filename = suggested_fname if suggested_fname.lower().endswith(".pdf") else f"{suggested_fname}.pdf"
            else:
                final_filename = "document_cropped.pdf"

        # Step 3: Crop margins
        logger.info(f"Starting margin cropping: {final_filename} (retain: {config.crop_percent}%)")
        await status_msg.edit_text(
            f"✂️ *Cropping margins with pdfCropMargins...*\nRetaining {config.crop_percent}% margin space.",
            parse_mode=ParseMode.MARKDOWN,
        )

        crop_ok, crop_msg = await crop_pdf(
            input_path=input_pdf_path,
            output_path=cropped_pdf_path,
            config=config,
        )

        if not crop_ok:
            logger.error(f"Margin cropping failed for {final_filename}: {crop_msg}")
            await status_msg.edit_text(f"❌ *Cropping error:*\n{crop_msg}", parse_mode=ParseMode.MARKDOWN)
            return

        # Step 4: Send cropped document back to chat
        logger.info(f"Uploading cropped file {final_filename} to chat {chat_id}...")
        await status_msg.edit_text("📤 *Uploading cropped document...*", parse_mode=ParseMode.MARKDOWN)
        try:
            with open(cropped_pdf_path, "rb") as doc_file:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=doc_file,
                    filename=final_filename,
                    caption=f"✂️ Cropped: *{document_title}*",
                    parse_mode=ParseMode.MARKDOWN,
                )
            await status_msg.delete()
            logger.info(f"Successfully sent {final_filename} to user {user.id}")
        except Exception as e:
            logger.exception(f"Failed to upload document {final_filename} to Telegram")
            await status_msg.edit_text(f"❌ Failed to upload document: {str(e)}")


async def handle_url_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text messages containing URLs or arXiv IDs."""
    if not await auth_check(update, context):
        return

    user = update.effective_user
    text = update.message.text or ""
    logger.info(f"Received text message from user {user.id} (@{user.username}): {text!r}")

    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        # Check if message is a bare arXiv ID
        arxiv_id = extract_arxiv_id(text)
        if arxiv_id:
            target_url = get_arxiv_pdf_url(arxiv_id)
            await process_pdf_job(target_url, update, context)
            return

        logger.info(f"No valid URL or arXiv ID found in message from user {user.id}")
        await update.message.reply_text(
            "Please send a valid PDF link or an arXiv paper URL.\n\n"
            "Examples:\n"
            "• `https://arxiv.org/abs/2609.19101`\n"
            "• `https://arxiv.org/pdf/2609.19101.pdf`\n"
            "• `https://example.com/paper.pdf`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target_url = url_match.group(0)
    await process_pdf_job(target_url, update, context)


async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles PDF documents directly uploaded to the Telegram bot."""
    if not await auth_check(update, context):
        return

    user = update.effective_user
    document = update.message.document
    if not document or not document.file_name:
        return

    logger.info(f"Received document upload from user {user.id} (@{user.username}): {document.file_name} ({document.file_size} bytes)")

    if not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Please upload a PDF document.")
        return

    config: Config = context.bot_data["config"]
    if document.file_size and document.file_size > (config.max_file_size_mb * 1024 * 1024):
        await update.message.reply_text(f"File size exceeds maximum limit of {config.max_file_size_mb} MB.")
        return

    status_msg = await update.message.reply_text("📥 Downloading uploaded document...", parse_mode=ParseMode.MARKDOWN)

    with tempfile.TemporaryDirectory() as tmp_dir:
        input_pdf_path = os.path.join(tmp_dir, "input.pdf")
        cropped_pdf_path = os.path.join(tmp_dir, "cropped.pdf")

        try:
            tg_file = await document.get_file()
            await tg_file.download_to_drive(input_pdf_path)

            await status_msg.edit_text("✂️ Cropping margins...", parse_mode=ParseMode.MARKDOWN)
            crop_ok, crop_msg = await crop_pdf(input_pdf_path, cropped_pdf_path, config)
            if not crop_ok:
                logger.error(f"Cropping failed for uploaded file {document.file_name}: {crop_msg}")
                await status_msg.edit_text(f"❌ Cropping error: {crop_msg}")
                return

            base_name = os.path.splitext(document.file_name)[0]
            final_filename = f"{base_name}_cropped.pdf"

            with open(cropped_pdf_path, "rb") as doc_file:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=doc_file,
                    filename=final_filename,
                    caption=f"✂️ Cropped: *{base_name}*",
                    parse_mode=ParseMode.MARKDOWN,
                )
            await status_msg.delete()
            logger.info(f"Successfully processed and sent uploaded PDF {final_filename} to user {user.id}")

        except Exception as e:
            logger.exception("Error processing uploaded document")
            await status_msg.edit_text(f"❌ Error processing document: {str(e)}")


def create_bot_app() -> Application:
    """Builds and configures the Telegram Bot application."""
    config = Config.from_env()
    if not config.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set!")

    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config

    # Register handlers
    app.add_handler(CommandHandler("start", command_start))
    app.add_handler(CommandHandler("help", command_start))
    app.add_handler(CommandHandler("status", command_status))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document_upload))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_url_message))

    return app


def main():
    logger.info("Starting pdfgram bot...")
    try:
        app = create_bot_app()
        app.run_polling(timeout=45, drop_pending_updates=True)
    except Exception as e:
        logger.critical(f"Bot failed to start: {e}")
        raise


if __name__ == "__main__":
    main()
