"""
Main Telegram bot module for pdfgram.
Handles messages, arXiv parsing, PDF cropping, and Kindle delivery.
"""

import os
import re
import time
import uuid
import json
import asyncio
import logging
import tempfile
from typing import Dict, Any, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import Config
from cropper import download_file, crop_pdf, read_pdf_title, extract_filename_from_url
from arxiv_utils import extract_arxiv_id, get_arxiv_pdf_url, fetch_arxiv_metadata, make_arxiv_filename
from kindle import send_to_kindle

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("pdfgram")

# In-memory storage for pending cropped files ready for callback queries
# Structure: {token: {"temp_dir": TemporaryDirectory, "output_path": str, "filename": str, "title": str, "created_at": float}}
PENDING_FILES: Dict[str, Dict[str, Any]] = {}

# File path for persisted user settings (e.g. Kindle emails)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def load_user_settings() -> dict:
    """Loads per-user settings from disk."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading settings file: {e}")
    return {}


def save_user_settings(settings: dict) -> None:
    """Saves per-user settings to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving settings file: {e}")


def get_user_kindle_email(user_id: int, default_email: str) -> str:
    """Returns the user's configured Kindle email, or the default from environment."""
    settings = load_user_settings()
    user_data = settings.get(str(user_id), {})
    return user_data.get("kindle_email", default_email)


def set_user_kindle_email(user_id: int, email: str) -> None:
    """Saves a user-specific Kindle email."""
    settings = load_user_settings()
    if str(user_id) not in settings:
        settings[str(user_id)] = {}
    settings[str(user_id)]["kindle_email"] = email
    save_user_settings(settings)


def cleanup_expired_pending_files(max_age_seconds: float = 3600.0) -> None:
    """Removes temporary files older than max_age_seconds."""
    now = time.time()
    expired_keys = [
        k for k, v in PENDING_FILES.items()
        if now - v.get("created_at", 0) > max_age_seconds
    ]
    for k in expired_keys:
        item = PENDING_FILES.pop(k, None)
        if item and "temp_dir" in item:
            try:
                item["temp_dir"].cleanup()
            except Exception:
                pass


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
        if update.message:
            await update.message.reply_text("⛔ Access denied: You are not authorized to use this bot.")
        elif update.callback_query:
            await update.callback_query.answer("⛔ Access denied.", show_alert=True)
        return False
    return True


async def command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start command."""
    if not await auth_check(update, context):
        return

    config: Config = context.bot_data["config"]
    user_id = update.effective_user.id
    current_kindle = get_user_kindle_email(user_id, config.kindle_email)

    msg = (
        "👋 *Welcome to pdfgram!* \n\n"
        "Send me a link to an **arXiv paper** or any **PDF file**, and I will:\n"
        "1. Download the document\n"
        "2. Automatically crop the margins using `pdfCropMargins`\n"
        "3. Rename arXiv papers with their ID and full title\n"
        "4. Send the cropped document back to this chat or to your Kindle!\n\n"
        "📚 *Usage:*\n"
        "• Just paste a link: `https://arxiv.org/abs/1706.03762`\n"
        "• Or send a direct PDF link: `https://example.com/paper.pdf`\n"
        "• Or upload a PDF document directly here\n\n"
        "⚙️ *Commands:*\n"
        f"• `/mykindle` — View Kindle & SMTP configuration\n"
        f"• `/setkindle <email>` — Set your personal Kindle email\n"
        f"• `/crop <url>` — Crop and receive directly in chat\n"
        f"• `/kindle <url>` — Crop and deliver straight to Kindle\n"
        f"• `/status` — View current bot settings\n\n"
        f"📱 *Your Kindle Email:* `{current_kindle or 'Not configured'}`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def command_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /help command."""
    await command_start(update, context)


async def command_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /status command."""
    if not await auth_check(update, context):
        return

    config: Config = context.bot_data["config"]
    user_id = update.effective_user.id
    kindle_email = get_user_kindle_email(user_id, config.kindle_email)
    smtp_ok = "✅ Configured" if config.smtp.is_configured else "❌ Not configured"

    msg = (
        "⚙️ *pdfgram Bot Status*\n\n"
        f"• *Crop Margin Retain:* `{config.crop_percent}%`\n"
        f"• *Uniform Cropping:* `{'Enabled' if config.crop_uniform else 'Disabled'}`\n"
        f"• *Same Page Size:* `{'Enabled' if config.crop_same_page_size else 'Disabled'}`\n"
        f"• *Default Action:* `{config.default_action}`\n"
        f"• *Kindle Recipient:* `{kindle_email or 'None'}`\n"
        f"• *SMTP Service:* {smtp_ok}\n"
        f"• *Max Download Size:* `{config.max_file_size_mb} MB`\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def command_mykindle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /mykindle command."""
    if not await auth_check(update, context):
        return

    config: Config = context.bot_data["config"]
    user_id = update.effective_user.id
    kindle_email = get_user_kindle_email(user_id, config.kindle_email)

    lines = [
        "📱 *Kindle Delivery Settings*",
        f"• **Destination Email:** `{kindle_email or 'Not set'}`",
        f"• **SMTP Status:** `{'Ready' if config.smtp.is_configured else 'Not configured'}`",
    ]

    if config.smtp.is_configured:
        lines.append(f"• **SMTP Host:** `{config.smtp.host}:{config.smtp.port}`")
        lines.append(f"• **Sender Email:** `{config.smtp.from_email or config.smtp.user}`")
        lines.append("\n⚠️ *Reminder:* Ensure the sender email is added to your Amazon account's "
                     "*Approved Personal Document E-mail List* in "
                     "_Manage Your Content and Devices → Preferences → Personal Document Settings_.")
    else:
        lines.append("\n💡 *Note:* To enable Kindle delivery, set SMTP variables (SMTP_HOST, SMTP_USER, SMTP_PASSWORD) in your environment.")

    lines.append("\nTo change your Kindle address: `/setkindle yourname@kindle.com`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def command_setkindle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /setkindle <email> command."""
    if not await auth_check(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Please provide an email address.\nUsage: `/setkindle yourname@kindle.com`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    email = args[0].strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ Invalid email format. Example: `/setkindle user@kindle.com`", parse_mode=ParseMode.MARKDOWN)
        return

    user_id = update.effective_user.id
    set_user_kindle_email(user_id, email)
    await update.message.reply_text(
        f"✅ Kindle address set to: `{email}`\n"
        "Any documents sent with Kindle delivery will now be emailed here.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def process_pdf_job(
    target_url: str,
    explicit_action: Optional[str],  # 'chat', 'kindle', or None (uses config.default_action)
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Core workflow for fetching, cropping, and dispatching a PDF."""
    config: Config = context.bot_data["config"]
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    cleanup_expired_pending_files()

    # Step 1: Check for arXiv URL / ID
    arxiv_id = extract_arxiv_id(target_url)
    arxiv_title = None
    download_url = target_url

    status_msg = await update.message.reply_text(
        "🔍 *Analyzing link...*",
        parse_mode=ParseMode.MARKDOWN,
    )

    if arxiv_id:
        download_url = get_arxiv_pdf_url(arxiv_id)
        await status_msg.edit_text(
            f"📄 *Detected arXiv paper:* `{arxiv_id}`\n⏳ Fetching metadata...",
            parse_mode=ParseMode.MARKDOWN,
        )
        arxiv_title, _ = await fetch_arxiv_metadata(arxiv_id)
        if arxiv_title:
            await status_msg.edit_text(
                f"📄 *arXiv:* `{arxiv_id}`\n"
                f"📌 *Title:* {arxiv_title}\n"
                "⏳ Downloading PDF document...",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await status_msg.edit_text(
                f"📄 *arXiv:* `{arxiv_id}`\n⏳ Downloading PDF document...",
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        await status_msg.edit_text(
            "📄 *PDF link detected.*\n⏳ Downloading document...",
            parse_mode=ParseMode.MARKDOWN,
        )

    # Step 2: Download PDF to a temporary directory
    tmp_dir = tempfile.TemporaryDirectory()
    input_pdf_path = os.path.join(tmp_dir.name, "input.pdf")
    cropped_pdf_path = os.path.join(tmp_dir.name, "cropped.pdf")

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)

    ok, error_msg, suggested_fname = await download_file(
        url=download_url,
        destination_path=input_pdf_path,
        max_size_mb=config.max_file_size_mb,
    )

    if not ok:
        tmp_dir.cleanup()
        await status_msg.edit_text(f"❌ *Download failed:*\n{error_msg}", parse_mode=ParseMode.MARKDOWN)
        return

    # Determine optimal output filename
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
    await status_msg.edit_text(
        f"✂️ *Cropping margins with pdfCropMargins...*\n"
        f"Retaining {config.crop_percent}% margin space.",
        parse_mode=ParseMode.MARKDOWN,
    )

    crop_ok, crop_msg = await crop_pdf(
        input_path=input_pdf_path,
        output_path=cropped_pdf_path,
        config=config,
    )

    if not crop_ok:
        tmp_dir.cleanup()
        await status_msg.edit_text(f"❌ *Cropping error:*\n{crop_msg}", parse_mode=ParseMode.MARKDOWN)
        return

    # Step 4: Dispatch according to action
    action = explicit_action or config.default_action
    user_kindle = get_user_kindle_email(user_id, config.kindle_email)
    can_kindle = config.smtp.is_configured and bool(user_kindle)

    # If action is 'kindle' but kindle is not configured, fall back to chat
    if action == "kindle" and not can_kindle:
        await update.message.reply_text(
            "⚠️ Kindle delivery requested, but Kindle email or SMTP is not configured. Falling back to sending here in chat."
        )
        action = "chat"

    # If action is 'ask' and Kindle is configured, prompt user with buttons
    if action == "ask" and can_kindle:
        token = str(uuid.uuid4())[:8]
        PENDING_FILES[token] = {
            "temp_dir": tmp_dir,
            "output_path": cropped_pdf_path,
            "filename": final_filename,
            "title": document_title,
            "created_at": time.time(),
        }

        filesize_mb = round(os.path.getsize(cropped_pdf_path) / (1024 * 1024), 2)
        keyboard = [
            [
                InlineKeyboardButton("📥 Send to Chat", callback_data=f"send:chat:{token}"),
                InlineKeyboardButton("📱 Send to Kindle", callback_data=f"send:kindle:{token}"),
            ],
            [
                InlineKeyboardButton("📦 Send to Both", callback_data=f"send:both:{token}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text(
            f"✅ *Margins cropped successfully!*\n\n"
            f"📄 *File:* `{final_filename}`\n"
            f"📏 *Size:* `{filesize_mb} MB`\n\n"
            "Choose where to send the document:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Direct delivery: Send to chat
    if action in ("chat", "both") or (action == "ask" and not can_kindle):
        await status_msg.edit_text("📤 *Uploading cropped document to Telegram...*", parse_mode=ParseMode.MARKDOWN)
        try:
            with open(cropped_pdf_path, "rb") as doc_file:
                # Add an inline button for Kindle if available
                buttons = []
                if can_kindle and action != "both":
                    token = str(uuid.uuid4())[:8]
                    PENDING_FILES[token] = {
                        "temp_dir": tmp_dir,
                        "output_path": cropped_pdf_path,
                        "filename": final_filename,
                        "title": document_title,
                        "created_at": time.time(),
                    }
                    buttons.append([InlineKeyboardButton("📱 Also Send to Kindle", callback_data=f"send:kindle:{token}")])

                reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=doc_file,
                    filename=final_filename,
                    caption=f"✂️ Cropped: *{document_title}*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            await status_msg.delete()
        except Exception as e:
            logger.exception("Failed to send document to Telegram")
            await status_msg.edit_text(f"❌ Failed to upload document: {str(e)}")

        # If not saved for pending Kindle button, clean up now
        if not (can_kindle and action != "both"):
            tmp_dir.cleanup()

    # Direct delivery: Send to Kindle
    if action in ("kindle", "both"):
        await status_msg.edit_text(f"📧 *Delivering to Kindle ({user_kindle})...*", parse_mode=ParseMode.MARKDOWN)
        send_ok, send_msg = await send_to_kindle(
            pdf_path=cropped_pdf_path,
            recipient_email=user_kindle,
            filename=final_filename,
            title=document_title,
            smtp_config=config.smtp,
        )
        if send_ok:
            await status_msg.edit_text(
                f"✅ *Delivered to Kindle!*\n"
                f"📄 `{final_filename}`\n"
                f"📬 Sent to `{user_kindle}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await status_msg.edit_text(
                f"❌ *Kindle delivery failed:*\n{send_msg}",
                parse_mode=ParseMode.MARKDOWN,
            )
        tmp_dir.cleanup()


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline keyboard button clicks."""
    query = update.callback_query
    await query.answer()

    if not await auth_check(update, context):
        return

    data = query.data
    if not data or not data.startswith("send:"):
        return

    parts = data.split(":")
    if len(parts) != 3:
        return

    target_action = parts[1]
    token = parts[2]

    pending = PENDING_FILES.get(token)
    if not pending:
        await query.edit_message_text("⚠️ This file session has expired. Please send the link again.")
        return

    config: Config = context.bot_data["config"]
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_kindle = get_user_kindle_email(user_id, config.kindle_email)

    output_path = pending["output_path"]
    filename = pending["filename"]
    title = pending["title"]
    tmp_dir = pending["temp_dir"]

    # Action 1: Send to Chat
    if target_action in ("chat", "both"):
        await query.edit_message_text(f"📤 Uploading `{filename}`...", parse_mode=ParseMode.MARKDOWN)
        try:
            with open(output_path, "rb") as doc_file:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=doc_file,
                    filename=filename,
                    caption=f"✂️ Cropped: *{title}*",
                    parse_mode=ParseMode.MARKDOWN,
                )
        except Exception as e:
            await query.message.reply_text(f"❌ Failed to upload document: {str(e)}")

    # Action 2: Send to Kindle
    if target_action in ("kindle", "both"):
        await query.edit_message_text(f"📧 Delivering `{filename}` to Kindle ({user_kindle})...", parse_mode=ParseMode.MARKDOWN)
        send_ok, send_msg = await send_to_kindle(
            pdf_path=output_path,
            recipient_email=user_kindle,
            filename=filename,
            title=title,
            smtp_config=config.smtp,
        )
        if send_ok:
            await query.edit_message_text(
                f"✅ *Delivered to Kindle!*\n"
                f"📄 `{filename}`\n"
                f"📬 Sent to `{user_kindle}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await query.edit_message_text(
                f"❌ *Kindle delivery failed:*\n{send_msg}",
                parse_mode=ParseMode.MARKDOWN,
            )

    if target_action == "chat":
        await query.edit_message_text(f"✅ Sent `{filename}` to chat.", parse_mode=ParseMode.MARKDOWN)

    # Cleanup temporary files
    PENDING_FILES.pop(token, None)
    try:
        tmp_dir.cleanup()
    except Exception:
        pass


async def handle_url_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages containing URLs."""
    if not await auth_check(update, context):
        return

    text = update.message.text or ""
    # Search for URL in message
    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        # Check if user typed arXiv ID directly e.g. "arxiv:2309.19101" or "2309.19101"
        arxiv_id = extract_arxiv_id(text)
        if arxiv_id:
            target_url = get_arxiv_pdf_url(arxiv_id)
            await process_pdf_job(target_url, None, update, context)
            return
        await update.message.reply_text(
            "Please send a valid PDF link or an arXiv paper URL.\n\n"
            "Examples:\n"
            "• `https://arxiv.org/abs/1706.03762`\n"
            "• `https://example.com/paper.pdf`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target_url = url_match.group(0)
    await process_pdf_job(target_url, None, update, context)


async def command_crop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explicit /crop <url> command."""
    if not await auth_check(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/crop <url>`", parse_mode=ParseMode.MARKDOWN)
        return

    target_url = args[0]
    await process_pdf_job(target_url, "chat", update, context)


async def command_kindle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explicit /kindle <url> command."""
    if not await auth_check(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/kindle <url>`", parse_mode=ParseMode.MARKDOWN)
        return

    target_url = args[0]
    await process_pdf_job(target_url, "kindle", update, context)


async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles PDF documents uploaded directly to the Telegram bot."""
    if not await auth_check(update, context):
        return

    document = update.message.document
    if not document or not document.file_name:
        return

    if not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Please upload a PDF document.")
        return

    config: Config = context.bot_data["config"]
    if document.file_size and document.file_size > (config.max_file_size_mb * 1024 * 1024):
        await update.message.reply_text(f"File size exceeds maximum limit of {config.max_file_size_mb} MB.")
        return

    status_msg = await update.message.reply_text("📥 Downloading uploaded document...", parse_mode=ParseMode.MARKDOWN)

    tmp_dir = tempfile.TemporaryDirectory()
    input_pdf_path = os.path.join(tmp_dir.name, "input.pdf")
    cropped_pdf_path = os.path.join(tmp_dir.name, "cropped.pdf")

    try:
        tg_file = await document.get_file()
        await tg_file.download_to_drive(input_pdf_path)

        await status_msg.edit_text("✂️ Cropping margins...", parse_mode=ParseMode.MARKDOWN)
        crop_ok, crop_msg = await crop_pdf(input_pdf_path, cropped_pdf_path, config)
        if not crop_ok:
            tmp_dir.cleanup()
            await status_msg.edit_text(f"❌ Cropping error: {crop_msg}")
            return

        base_name = os.path.splitext(document.file_name)[0]
        final_filename = f"{base_name}_cropped.pdf"

        # Offer delivery or send back
        user_id = update.effective_user.id
        user_kindle = get_user_kindle_email(user_id, config.kindle_email)
        can_kindle = config.smtp.is_configured and bool(user_kindle)

        if can_kindle:
            token = str(uuid.uuid4())[:8]
            PENDING_FILES[token] = {
                "temp_dir": tmp_dir,
                "output_path": cropped_pdf_path,
                "filename": final_filename,
                "title": base_name,
                "created_at": time.time(),
            }
            keyboard = [
                [
                    InlineKeyboardButton("📥 Send to Chat", callback_data=f"send:chat:{token}"),
                    InlineKeyboardButton("📱 Send to Kindle", callback_data=f"send:kindle:{token}"),
                ],
                [
                    InlineKeyboardButton("📦 Send to Both", callback_data=f"send:both:{token}"),
                ]
            ]
            await status_msg.edit_text(
                f"✅ *Cropped:* `{final_filename}`\nWhere would you like to send it?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            with open(cropped_pdf_path, "rb") as doc_file:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=doc_file,
                    filename=final_filename,
                    caption=f"✂️ Cropped: *{base_name}*",
                    parse_mode=ParseMode.MARKDOWN,
                )
            await status_msg.delete()
            tmp_dir.cleanup()

    except Exception as e:
        tmp_dir.cleanup()
        logger.exception("Error processing uploaded document")
        await status_msg.edit_text(f"❌ Error processing document: {str(e)}")


def create_bot_app() -> Application:
    """Builds and configures the Telegram Bot application."""
    config = Config.from_env()
    if not config.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set!")

    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config

    # Register Command Handlers
    app.add_handler(CommandHandler("start", command_start))
    app.add_handler(CommandHandler("help", command_help))
    app.add_handler(CommandHandler("status", command_status))
    app.add_handler(CommandHandler("mykindle", command_mykindle))
    app.add_handler(CommandHandler("setkindle", command_setkindle))
    app.add_handler(CommandHandler("crop", command_crop))
    app.add_handler(CommandHandler("kindle", command_kindle))

    # Register Callback Query Handler for Inline Buttons
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Register Message Handlers
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document_upload))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_url_message))

    return app


def main():
    logger.info("Starting pdfgram bot...")
    try:
        app = create_bot_app()
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.critical(f"Bot failed to start: {e}")
        raise


if __name__ == "__main__":
    main()
