"""
Configuration management for pdfgram bot.
Loads settings from environment variables and .env file.
"""

import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    telegram_bot_token: str
    allowed_user_ids: List[int]
    crop_percent: int = 10
    crop_uniform: bool = True
    crop_same_page_size: bool = False
    crop_extra_args: str = ""
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
            max_file_size_mb=max_file_size_mb,
        )
