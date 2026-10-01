import asyncio

import pytest

from app.services.downloader import (
    DownloadArtifact, DownloadError, DownloadManager, DownloadResult,
)
from app.services.validator import Platform


@pytest.mark.asyncio
async def test_claim_rejects_second_request_for_same_user(tmp_path) -> None:
    manager = DownloadManager(1, 30, 50 * 1024 * 1024, tmp_path / "temp")
    lock, claimed = await manager.claim(42, "https://tiktok.com/video/one")
    assert claimed is True

    second_lock, second_claimed = await manager.claim(
        42, "https://instagram.com/reel/two"
    )
    assert second_claimed is False
    assert second_lock.locked() is False

    await manager.release("https://tiktok.com/video/one")
    assert manager.user_locks == {}


@pytest.mark.asyncio
async def test_close_cancels_queued_downloads(tmp_path, monkeypatch) -> None:
    manager = DownloadManager(1, 30, 50 * 1024 * 1024, tmp_path / "temp")

    async def slow_download(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(manager, "_download_direct", slow_download)
    first = asyncio.create_task(
        manager.download(
            "https://tiktok.com/video/one",
            Platform.TIKTOK,
            tmp_path / "downloads",
        )
    )
    second = asyncio.create_task(
        manager.download(
            "https://tiktok.com/video/two",
            Platform.TIKTOK,
            tmp_path / "downloads",
        )
    )
    await asyncio.sleep(0)
    await manager.close()

    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(asyncio.CancelledError):
        await second


@pytest.mark.asyncio
async def test_claim_many_reserves_and_releases_complete_batch(tmp_path) -> None:
    manager = DownloadManager(1, 30, 50 * 1024 * 1024, tmp_path / "temp")
    urls = ["https://tiktok.com/1", "https://instagram.com/2"]
    lock, claimed = await manager.claim_many(42, urls)
    assert claimed is True
    assert lock.locked() is False

    _, duplicate_claimed = await manager.claim(99, urls[1])
    assert duplicate_claimed is False

    await manager.release_many(urls)
    assert manager.in_flight_urls == {}
    assert manager.user_locks == {}


def test_multi_artifact_result_reports_total_size_and_count(tmp_path) -> None:
    result = DownloadResult(
        artifacts=(
            DownloadArtifact(tmp_path / "1.jpg", 100, None, None, "photo"),
            DownloadArtifact(tmp_path / "2.mp4", 250, 4.5, "clip", "video"),
        ),
        platform=Platform.INSTAGRAM,
    )
    assert result.media_count == 2
    assert result.size_bytes == 350
    assert result.duration == 4.5
    assert result.path.name == "1.jpg"


def test_failed_ytdlp_does_not_accept_partial_file(tmp_path) -> None:
    partial = tmp_path / "video.mp4.part"
    partial.write_bytes(b"partial")
    assert DownloadManager._read_output_path(
        "", tmp_path, allow_fallback=False
    ) is None


@pytest.mark.asyncio
async def test_instagram_post_prefers_gallery_engine(tmp_path, monkeypatch) -> None:
    manager = DownloadManager(
        1, 30, 50 * 1024 * 1024, tmp_path / "temp", retry_base_delay=0
    )
    calls = []
    expected = DownloadResult(
        (DownloadArtifact(tmp_path / "image.jpg", 12, None, None, "photo"),),
        Platform.INSTAGRAM,
    )

    async def gallery(*args):
        calls.append("gallery")
        return expected

    async def ytdlp(*args):
        calls.append("ytdlp")
        raise AssertionError("video engine should not run after gallery succeeds")

    monkeypatch.setattr(manager, "_download_gallery", gallery)
    monkeypatch.setattr(manager, "_download_ytdlp", ytdlp)
    result = await manager._download_direct(
        "https://www.instagram.com/p/ABC/", Platform.INSTAGRAM, tmp_path / "out"
    )
    assert result is expected
    assert calls == ["gallery"]


@pytest.mark.asyncio
async def test_instagram_story_falls_back_to_gallery(tmp_path, monkeypatch) -> None:
    manager = DownloadManager(
        1, 30, 50 * 1024 * 1024, tmp_path / "temp", retry_base_delay=0
    )
    calls = []
    expected = DownloadResult(
        (DownloadArtifact(tmp_path / "story.mp4", 12, 2.0, None, "video"),),
        Platform.INSTAGRAM,
    )

    async def ytdlp(*args):
        calls.append("ytdlp")
        raise DownloadError("extractor failed")

    async def gallery(*args):
        calls.append("gallery")
        return expected

    monkeypatch.setattr(manager, "_download_ytdlp", ytdlp)
    monkeypatch.setattr(manager, "_download_gallery", gallery)
    result = await manager._download_direct(
        "https://www.instagram.com/stories/user/123/",
        Platform.INSTAGRAM,
        tmp_path / "out",
    )
    assert result is expected
    assert calls == ["ytdlp", "ytdlp", "gallery"]


@pytest.mark.asyncio
async def test_transient_engine_failure_is_retried(tmp_path) -> None:
    manager = DownloadManager(
        1, 30, 50 * 1024 * 1024, tmp_path / "temp",
        engine_attempts=3, retry_base_delay=0,
    )
    attempts = 0
    expected = DownloadResult(
        (DownloadArtifact(tmp_path / "video.mp4", 12, 2.0, None, "video"),),
        Platform.TIKTOK,
    )

    async def flaky(*args):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise DownloadError("Download timed out")
        return expected

    result = await manager._run_engine(
        flaky, "https://tiktok.com/video/1", Platform.TIKTOK,
        tmp_path / "out", None, "best", None,
    )
    assert result is expected
    assert attempts == 3


@pytest.mark.asyncio
async def test_permanent_engine_failure_is_not_retried(tmp_path) -> None:
    manager = DownloadManager(
        1, 30, 50 * 1024 * 1024, tmp_path / "temp",
        engine_attempts=3, retry_base_delay=0,
    )
    attempts = 0

    async def denied(*args):
        nonlocal attempts
        attempts += 1
        raise DownloadError("Instagram requires authentication for this request")

    with pytest.raises(DownloadError):
        await manager._run_engine(
            denied, "https://instagram.com/stories/user/1", Platform.INSTAGRAM,
            tmp_path / "out", None, "best", None,
        )
    assert attempts == 1


@pytest.mark.asyncio
async def test_download_workers_are_replenished_after_exit(tmp_path) -> None:
    manager = DownloadManager(2, 30, 50 * 1024 * 1024, tmp_path / "temp")

    async def finished_worker():
        return None

    stale = asyncio.create_task(finished_worker())
    await stale
    manager.worker_tasks = [stale]
    await manager._ensure_workers()
    try:
        assert len(manager.worker_tasks) == 2
        assert all(not task.done() for task in manager.worker_tasks)
    finally:
        await manager.close()
