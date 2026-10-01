from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    database_url: str
    max_file_size_mb: int
    download_timeout: int
    max_concurrent_downloads: int
    max_batch_size: int
    max_media_per_post: int
    engine_attempts: int
    retry_base_delay: int
    rate_limit_seconds: int
    max_requests_per_minute: int
    cooldown_seconds: int
    temp_retention_minutes: int
    log_level: str
    default_language: str
    auto_delete: bool
    drop_pending_updates: bool
    port: int
    instagram_cookies_base64: str = field(repr=False)
    root_dir: Path = ROOT_DIR

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def database_path(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            return self.root_dir / self.database_url.removeprefix("sqlite:///")
        return self.root_dir / "bot.db"

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        raw_admins = os.getenv("ADMIN_IDS", "")
        admin_ids: set[int] = set()
        for value in raw_admins.split(","):
            value = value.strip()
            if value:
                try:
                    admin_ids.add(int(value))
                except ValueError:
                    continue
        language = os.getenv("DEFAULT_LANGUAGE", "ar").strip().lower()
        if language not in {"ar", "en"}:
            language = "ar"
        return cls(
            bot_token=token,
            admin_ids=frozenset(admin_ids),
            database_url=os.getenv("DATABASE_URL", "sqlite:///bot.db"),
            max_file_size_mb=_int_env("MAX_FILE_SIZE_MB", 50, 1),
            download_timeout=_int_env("DOWNLOAD_TIMEOUT", 120, 10),
            max_concurrent_downloads=_int_env("MAX_CONCURRENT_DOWNLOADS", 3, 1),
            max_batch_size=_int_env("MAX_BATCH_SIZE", 5, 2),
            max_media_per_post=_int_env("MAX_MEDIA_PER_POST", 10, 1),
            engine_attempts=min(_int_env("ENGINE_ATTEMPTS", 2, 1), 4),
            retry_base_delay=min(_int_env("RETRY_BASE_DELAY", 2, 0), 15),
            rate_limit_seconds=_int_env("RATE_LIMIT_SECONDS", 10, 0),
            max_requests_per_minute=_int_env("MAX_REQUESTS_PER_MINUTE", 6, 1),
            cooldown_seconds=_int_env("COOLDOWN_SECONDS", 3, 0),
            temp_retention_minutes=_int_env("TEMP_RETENTION_MINUTES", 60, 1),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            default_language=language,
            auto_delete=_bool_env("AUTO_DELETE", True),
            drop_pending_updates=_bool_env("DROP_PENDING_UPDATES", False),
            port=_int_env("PORT", 0, 0),
            instagram_cookies_base64=os.getenv("INSTAGRAM_COOKIES_BASE64", "").strip(),
        )

    def validate(self) -> None:
        if not self.bot_token:
            raise RuntimeError(
                "BOT_TOKEN is required. Set it in Replit Secrets or your Railway environment."
            )
        if not re.fullmatch(r"\d{8,12}:[A-Za-z0-9_-]{30,}", self.bot_token):
            raise RuntimeError(
                "BOT_TOKEN has an invalid format. Paste only the raw BotFather token "
                "(no BOT_TOKEN= prefix, spaces, or extra text)."
            )
