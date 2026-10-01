import pytest

from app.services.validator import Platform, extract_urls, sanitize_filename, validate_url


def test_detects_tiktok() -> None:
    assert validate_url("https://www.tiktok.com/@creator/video/123").platform == Platform.TIKTOK


def test_detects_instagram_reel() -> None:
    assert validate_url("https://www.instagram.com/reel/ABC123/").platform == Platform.INSTAGRAM


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/stories/creator/123456789/",
        "https://www.instagram.com/p/ABC123/",
        "https://www.instagram.com/tv/ABC123/",
        "https://www.instagram.com/share/reel/ABC123/?igsh=test",
    ],
)
def test_detects_instagram_story_post_and_share_links(url: str) -> None:
    assert validate_url(url).platform == Platform.INSTAGRAM


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video",
        "http://localhost/file",
        "http://127.0.0.1/file",
        "https://tiktok.com:8080/video",
        "javascript:alert(1)",
    ],
)
def test_rejects_unsafe_or_unsupported_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_url(url)


def test_sanitizes_filename() -> None:
    assert sanitize_filename("../../video?.mp4") == "video.mp4"


def test_extracts_unique_supported_urls_for_batch() -> None:
    items = extract_urls(
        "first https://www.tiktok.com/@creator/video/123\n"
        "ignored https://example.com/nope\n"
        "second https://www.instagram.com/reel/ABC123/\n"
        "duplicate https://www.tiktok.com/@creator/video/123",
        limit=5,
    )
    assert [item.platform for item in items] == [Platform.TIKTOK, Platform.INSTAGRAM]
    assert len(items) == 2


def test_batch_extraction_respects_limit() -> None:
    text = " ".join(f"https://www.tiktok.com/@creator/video/{index}" for index in range(10))
    assert len(extract_urls(text, limit=3)) == 3
