from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path


logger = logging.getLogger(__name__)


def remove_path(path: Path) -> None:
    if path.is_dir():
        for child in path.iterdir():
            remove_path(child)
        path.rmdir()
    elif path.exists():
        path.unlink()


def cleanup_old_files(directory: Path, max_age_seconds: int) -> int:
    if not directory.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for child in directory.iterdir():
        try:
            if child.stat().st_mtime < cutoff:
                remove_path(child)
                removed += 1
        except FileNotFoundError:
            continue
    return removed


async def cleanup_loop(directories: list[Path], retention_minutes: int) -> None:
    while True:
        try:
            for directory in directories:
                removed = await asyncio.to_thread(
                    cleanup_old_files, directory, retention_minutes * 60
                )
                if removed:
                    logger.info("Cleaned %s temporary items from %s", removed, directory)
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background cleanup failed")