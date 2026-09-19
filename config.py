"""
Configuration management for pdfgram bot.
Loads settings from environment variables and .env file.
"""

import os
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class SmtpConfig:
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    from_email: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.user and self.password)


@dataclass
class Config:
    telegram_bot_token: str
    allowed_user_ids: List[int]
    crop_percent: int = 10
    crop_uniform: bool = True
    crop_same_page_size: bool = False
    crop_extra_args: str = ""
    default_action: str = "ask"  # 'ask', 'chat', 'kindle', 'both'
    kindle_email: str = ""
    smtp: SmtpConfig = None
    max_file_size_mb: int = 50

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

        # Parse allowed user IDs (comma-separated list)
        raw_ids = os.getenv("ALLOWED_USER_IDS", "").strip()
        allowed_ids = []
        if raw_ids:
            for piece in raw_ids.split(","):
                piece = piece.strip()
                if piece.isdigit() or (piece.startswith("-") and piece[1:].isdigit()):
                    allowed_ids.append(int(piece))

        # Crop settings
        try:
            crop_percent = int(os.getenv("CROP_PERCENT", "10"))
        except ValueError:
            crop_percent = 10

        crop_uniform = os.getenv("CROP_UNIFORM", "true").lower() in ("true", "1", "yes")
        crop_same_page_size = os.getenv("CROP_SAME_PAGE_SIZE", "false").lower() in ("true", "1", "yes")
        crop_extra_args = os.getenv("CROP_EXTRA_ARGS", "").strip()

        kindle_email = os.getenv("KINDLE_EMAIL", "").strip()

        # SMTP settings
        smtp_host = os.getenv("SMTP_HOST", "").strip()
        try:
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
        except ValueError:
            smtp_port = 587
        smtp_user = os.getenv("SMTP_USER", "").strip()
        smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
        smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
        smtp_use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() in ("true", "1", "yes")
        smtp_from = os.getenv("SMTP_FROM", "").strip() or smtp_user

        smtp = SmtpConfig(
            host=smtp_host,
            port=smtp_port,
            user=smtp_user,
            password=smtp_password,
            use_tls=smtp_use_tls,
            use_ssl=smtp_use_ssl,
            from_email=smtp_from,
        )

        # Default action
        action = os.getenv("DEFAULT_ACTION", "").strip().lower()
        if action not in ("ask", "chat", "kindle", "both"):
            action = "ask" if (smtp.is_configured and kindle_email) else "chat"

        try:
            max_file_size_mb = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
        except ValueError:
            max_file_size_mb = 50

        return cls(
            telegram_bot_token=token,
            allowed_user_ids=allowed_ids,
            crop_percent=crop_percent,
            crop_uniform=crop_uniform,
            crop_same_page_size=crop_same_page_size,
            crop_extra_args=crop_extra_args,
            default_action=action,
            kindle_email=kindle_email,
            smtp=smtp,
            max_file_size_mb=max_file_size_mb,
        )
