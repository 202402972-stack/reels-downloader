from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class Platform(StrEnum):
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    url: str
    platform: Platform


ALLOWED_HOSTS: dict[Platform, tuple[str, ...]] = {
    Platform.TIKTOK: ("tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"),
    Platform.INSTAGRAM: ("instagram.com", "www.instagram.com", "instagr.am"),
}


def _is_allowed_host(host: str, allowed: tuple[str, ...]) -> bool:
    normalized = host.lower().rstrip(".")
    return any(normalized == item or normalized.endswith(f".{item}") for item in allowed)


def _is_private_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host in {"localhost", "localhost.localdomain"} or host.endswith(".local")
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def validate_url(raw_url: str) -> ValidatedUrl:
    value = raw_url.strip()
    if len(value) > 2048:
        raise ValueError("URL is too long")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must use http or https")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("URL contains unsupported credentials or port")
    host = parsed.hostname.lower().rstrip(".")
    if _is_private_host(host):
        raise ValueError("Private hosts are not allowed")
    for platform, hosts in ALLOWED_HOSTS.items():
        if _is_allowed_host(host, hosts):
            return ValidatedUrl(value, platform)
    raise ValueError("Unsupported platform")


def extract_urls(text: str, limit: int = 5) -> list[ValidatedUrl]:
    """Extract, validate and de-duplicate supported URLs from a Telegram message."""
    candidates = re.findall(r"https?://[^\s<>]+", text, flags=re.IGNORECASE)
    results: list[ValidatedUrl] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.rstrip(".,;:!?)]}\"'")
        try:
            validated = validate_url(candidate)
        except ValueError:
            continue
        if validated.url in seen:
            continue
        seen.add(validated.url)
        results.append(validated)
        if len(results) >= limit:
            break
    return results


def sanitize_filename(name: str, fallback: str = "video") -> str:
    clean = re.sub(r"[^\w\s.-]", "", name, flags=re.UNICODE)
    clean = re.sub(r"\s+", "_", clean).strip("._")
    clean = clean[:96] or fallback
    return clean if clean.lower().endswith(".mp4") else f"{clean}.mp4"
