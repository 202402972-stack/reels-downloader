from __future__ import annotations

import base64
import binascii
from pathlib import Path


MAX_COOKIE_BYTES = 2 * 1024 * 1024


def materialize_instagram_cookies(encoded: str, temp_root: Path) -> Path | None:
    """Decode an optional Netscape cookies file without exposing it in logs."""
    if not encoded:
        return None
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("INSTAGRAM_COOKIES_BASE64 is not valid base64") from exc
    if not payload or len(payload) > MAX_COOKIE_BYTES:
        raise ValueError("Instagram cookies file is empty or too large")
    text = payload.decode("utf-8", errors="strict")
    if "Netscape HTTP Cookie File" not in text or "instagram.com" not in text.lower():
        raise ValueError("Instagram cookies must use Netscape cookies.txt format")
    temp_root.mkdir(parents=True, exist_ok=True)
    path = temp_root / "instagram-cookies.txt"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path
