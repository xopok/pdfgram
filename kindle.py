"""
Email delivery module for Amazon Send-to-Kindle.
Sends cropped and renamed documents to user's @kindle.com address via SMTP.
"""

import os
import ssl
import smtplib
import asyncio
import logging
from email.message import EmailMessage
from typing import Optional, Tuple
from config import SmtpConfig

logger = logging.getLogger(__name__)

# Amazon's limit for email attachments is 25 MB (or 50MB via Web, but 25MB via SMTP)
KINDLE_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def send_to_kindle_sync(
    pdf_path: str,
    recipient_email: str,
    filename: str,
    title: Optional[str],
    smtp_config: SmtpConfig,
    timeout: float = 45.0,
) -> Tuple[bool, str]:
    """
    Sends a PDF file to the specified Kindle email address via SMTP.
    """
    if not recipient_email:
        return False, "Kindle recipient email is not configured."

    if not smtp_config or not smtp_config.is_configured:
        return False, "SMTP settings (host, user, password) are not configured."

    if not os.path.exists(pdf_path):
        return False, f"PDF file not found: {pdf_path}"

    file_size = os.path.getsize(pdf_path)
    if file_size > KINDLE_MAX_ATTACHMENT_BYTES:
        mb = round(file_size / (1024 * 1024), 2)
        return False, f"File size ({mb} MB) exceeds Amazon Kindle's 25 MB email attachment limit."

    # Build Email Message
    msg = EmailMessage()
    from_addr = smtp_config.from_email or smtp_config.user
    msg["From"] = from_addr
    msg["To"] = recipient_email
    subject = title or filename
    # Remove any newlines or invalid headers from subject
    subject = " ".join(subject.split())
    msg["Subject"] = subject
    msg.set_content(f"Sent by pdfgram bot.\nFile: {filename}\n")

    try:
        with open(pdf_path, "rb") as f:
            pdf_data = f.read()

        msg.add_attachment(
            pdf_data,
            maintype="application",
            subtype="pdf",
            filename=filename,
        )
    except Exception as e:
        logger.exception("Failed to read PDF file for email attachment")
        return False, f"Could not read attachment: {str(e)}"

    # Connect to SMTP server and send
    try:
        if smtp_config.use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_config.host, smtp_config.port, context=context, timeout=timeout) as server:
                if smtp_config.user and smtp_config.password:
                    server.login(smtp_config.user, smtp_config.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=timeout) as server:
                if smtp_config.use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                if smtp_config.user and smtp_config.password:
                    server.login(smtp_config.user, smtp_config.password)
                server.send_message(msg)

        logger.info(f"Successfully sent {filename} to Kindle ({recipient_email}) via {smtp_config.host}")
        return True, f"Successfully delivered to {recipient_email}"

    except smtplib.SMTPAuthenticationError:
        return False, "SMTP Authentication failed: Check your SMTP username/password or app password."
    except smtplib.SMTPConnectError as e:
        return False, f"Could not connect to SMTP server {smtp_config.host}:{smtp_config.port}: {str(e)}"
    except Exception as e:
        logger.exception("Failed to send email to Kindle")
        return False, f"SMTP delivery error: {str(e)}"


async def send_to_kindle(
    pdf_path: str,
    recipient_email: str,
    filename: str,
    title: Optional[str],
    smtp_config: SmtpConfig,
) -> Tuple[bool, str]:
    """Async wrapper around send_to_kindle_sync using a thread executor."""
    return await asyncio.to_thread(
        send_to_kindle_sync,
        pdf_path,
        recipient_email,
        filename,
        title,
        smtp_config,
    )
