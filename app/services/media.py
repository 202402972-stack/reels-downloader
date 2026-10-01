from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    size_bytes: int
    duration: float | None
    title: str | None


def inspect_media(path: Path, duration: float | None = None, title: str | None = None) -> MediaInfo:
    return MediaInfo(path=path, size_bytes=path.stat().st_size, duration=duration, title=title)


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"