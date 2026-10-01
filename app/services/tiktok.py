from __future__ import annotations

from pathlib import Path

from .downloader import DownloadManager, DownloadResult
from .validator import Platform


class TikTokService:
    def __init__(self, downloader: DownloadManager) -> None:
        self.downloader = downloader

    async def download(
        self, url: str, output_dir: Path, progress_callback=None, quality: str = "best", owner_id: int | None = None
    ) -> DownloadResult:
        return await self.downloader.download(
            url, Platform.TIKTOK, output_dir, progress_callback=progress_callback,
            quality=quality, owner_id=owner_id,
        )