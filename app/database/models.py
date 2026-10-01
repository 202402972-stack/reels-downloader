from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


DownloadStatus = Literal["queued", "downloading", "completed", "failed", "too_large"]


@dataclass(slots=True)
class User:
    telegram_id: int
    username: str | None
    first_name: str
    language: str
    downloads_count: int = 0
    created_at: datetime | None = None
    last_activity: datetime | None = None
    is_blocked: bool = False


@dataclass(slots=True)
class DownloadRecord:
    id: int
    telegram_user_id: int
    platform: str
    url: str
    status: DownloadStatus
    file_size: int | None
    duration: float | None
    created_at: datetime


@dataclass(slots=True)
class PlatformStats:
    total: int
    tiktok: int
    instagram: int
    failed: int