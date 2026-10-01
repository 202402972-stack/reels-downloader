from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from ..config import Settings
from ..database.repository import UserRepository
from ..services.downloader import DownloadManager
from ..services.instagram import InstagramService
from ..services.rate_limiter import RateLimiter
from ..services.tiktok import TikTokService
from .localization import Translator


@dataclass(slots=True)
class AppContext:
    settings: Settings
    users: UserRepository
    downloader: DownloadManager
    tiktok: TikTokService
    instagram: InstagramService
    rate_limiter: RateLimiter
    translator: Translator
    started_at: float = field(default_factory=monotonic)