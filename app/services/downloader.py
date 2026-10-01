from __future__ import annotations

import asyncio
import logging
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Literal

from .media import inspect_media
from .validator import Platform


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int | None, str | None], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class DownloadArtifact:
    path: Path
    size_bytes: int
    duration: float | None
    title: str | None
    kind: Literal["video", "photo"]


@dataclass(frozen=True, slots=True)
class DownloadResult:
    artifacts: tuple[DownloadArtifact, ...]
    platform: Platform

    @property
    def path(self) -> Path:
        return self.artifacts[0].path

    @property
    def size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.artifacts)

    @property
    def duration(self) -> float | None:
        durations = [item.duration for item in self.artifacts if item.duration is not None]
        return sum(durations) if durations else None

    @property
    def title(self) -> str | None:
        return self.artifacts[0].title

    @property
    def media_count(self) -> int:
        return len(self.artifacts)


class DownloadError(RuntimeError):
    pass


class DownloadManager:
    def __init__(
        self,
        max_concurrent: int,
        timeout_seconds: int,
        max_file_size_bytes: int,
        temp_root: Path,
        instagram_cookies_file: Path | None = None,
        max_media_per_post: int = 10,
        engine_attempts: int = 2,
        retry_base_delay: int = 2,
    ) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.user_locks: dict[int, asyncio.Lock] = {}
        self.in_flight_urls: dict[str, int] = {}
        self.state_lock = asyncio.Lock()
        self.queue: asyncio.Queue[
            tuple[str, Platform, Path, ProgressCallback | None, asyncio.Future, str, int | None]
        ] = asyncio.Queue()
        self.worker_count = max_concurrent
        self.worker_tasks: list[asyncio.Task] = []
        self.timeout_seconds = timeout_seconds
        self.max_file_size_bytes = max_file_size_bytes
        self.temp_root = temp_root
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.instagram_cookies_file = instagram_cookies_file
        self.max_media_per_post = max(1, min(max_media_per_post, 10))
        self.engine_attempts = max(1, min(engine_attempts, 4))
        self.retry_base_delay = max(0, min(retry_base_delay, 15))
        self.active_processes: dict[int, asyncio.subprocess.Process] = {}
        self.cancel_requested: set[int] = set()
        self.engine_metrics: dict[str, dict[str, int]] = {
            "yt_dlp": {"attempts": 0, "successes": 0, "failures": 0},
            "gallery_dl": {"attempts": 0, "successes": 0, "failures": 0},
        }
        self.last_engine_error: str | None = None

    async def claim(self, user_id: int, url: str) -> tuple[asyncio.Lock, bool]:
        return await self.claim_many(user_id, [url])

    async def claim_many(self, user_id: int, urls: list[str]) -> tuple[asyncio.Lock, bool]:
        async with self.state_lock:
            lock = self.user_locks.get(user_id)
            # A per-user lock is not enough here: a task can be waiting for it
            # without having acquired it yet. Track ownership explicitly so a
            # second request is rejected immediately and predictably.
            if any(url in self.in_flight_urls for url in urls) or (lock is not None and lock.locked()) or any(
                owner == user_id for owner in self.in_flight_urls.values()
            ):
                return asyncio.Lock(), False
            if lock is None:
                lock = asyncio.Lock()
                self.user_locks[user_id] = lock
            for url in urls:
                self.in_flight_urls[url] = user_id
            return lock, True

    async def release(self, url: str) -> None:
        async with self.state_lock:
            user_id = self.in_flight_urls.pop(url, None)
            if user_id is not None and not any(
                owner == user_id for owner in self.in_flight_urls.values()
            ):
                self.user_locks.pop(user_id, None)

    async def release_many(self, urls: list[str]) -> None:
        for url in urls:
            await self.release(url)

    async def _ensure_workers(self) -> None:
        alive: list[asyncio.Task] = []
        for task in self.worker_tasks:
            if task.done():
                if not task.cancelled():
                    try:
                        task.exception()
                    except Exception:
                        logger.exception("Download worker exited unexpectedly")
            else:
                alive.append(task)
        self.worker_tasks = alive
        for index in range(len(alive), self.worker_count):
            self.worker_tasks.append(
                asyncio.create_task(self._worker(), name=f"download-worker-{index}")
            )

    async def _worker(self) -> None:
        while True:
            url, platform, output_dir, callback, future, quality, owner_id = await self.queue.get()
            try:
                result = await self._download_direct(url, platform, output_dir, callback, quality, owner_id)
                if not future.cancelled():
                    future.set_result(result)
            except asyncio.CancelledError:
                if not future.cancelled():
                    future.cancel()
                raise
            except Exception as exc:
                if not future.cancelled():
                    future.set_exception(exc)
            finally:
                self.queue.task_done()

    async def close(self) -> None:
        processes = [
            process for process in self.active_processes.values()
            if process.returncode is None
        ]
        for process in processes:
            process.kill()
        if processes:
            await asyncio.gather(
                *(process.wait() for process in processes), return_exceptions=True
            )
        # Cancel queued futures before stopping workers; otherwise callers
        # awaiting DownloadManager.download() can hang forever.
        while not self.queue.empty():
            try:
                _, _, _, _, future, _, _ = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not future.done():
                future.cancel()
            self.queue.task_done()
        for task in self.worker_tasks:
            task.cancel()
        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks, return_exceptions=True)
        self.worker_tasks.clear()

    async def download(
        self,
        url: str,
        platform: Platform,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        quality: str = "best",
        owner_id: int | None = None,
    ) -> DownloadResult:
        await self._ensure_workers()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[DownloadResult] = loop.create_future()
        await self.queue.put(
            (url, platform, output_dir, progress_callback, future, quality, owner_id)
        )
        return await future

    async def _download_direct(
        self,
        url: str,
        platform: Platform,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        quality: str = "best",
        owner_id: int | None = None,
    ) -> DownloadResult:
        if platform != Platform.INSTAGRAM:
            return await self._run_engine(
                self._download_ytdlp, url, platform, output_dir,
                progress_callback, quality, owner_id,
            )

        # gallery-dl is the stronger first choice for Instagram posts because it
        # preserves image-only and carousel posts. yt-dlp remains the primary
        # video/story path and a fallback for extractor-specific regressions.
        is_post = bool(re.search(r"instagram\.com/(?:p|tv)/", url, re.IGNORECASE))
        engines = (
            (self._download_gallery, self._download_ytdlp)
            if is_post
            else (self._download_ytdlp, self._download_gallery)
        )
        failures: list[str] = []
        for engine in engines:
            if owner_id is not None and owner_id in self.cancel_requested:
                raise DownloadError("Download canceled")
            try:
                return await self._run_engine(
                    engine, url, platform, output_dir,
                    progress_callback, quality, owner_id,
                )
            except DownloadError as exc:
                if "canceled" in str(exc).lower():
                    raise
                failures.append(str(exc))
                logger.info("Instagram engine %s failed; trying fallback", engine.__name__)
        if self.instagram_cookies_file is None and any(
            token in " ".join(failures).lower()
            for token in ("login", "authentication", "unreachable", "rate-limit")
        ):
            raise DownloadError("Instagram requires login; configure cookies for this content")
        raise DownloadError(failures[-1] if failures else "Instagram download failed")

    async def _run_engine(
        self,
        engine,
        url: str,
        platform: Platform,
        output_dir: Path,
        progress_callback: ProgressCallback | None,
        quality: str,
        owner_id: int | None,
    ) -> DownloadResult:
        metric_key = "gallery_dl" if engine.__name__ == "_download_gallery" else "yt_dlp"
        last_error: DownloadError | None = None
        for attempt in range(1, self.engine_attempts + 1):
            self.engine_metrics[metric_key]["attempts"] += 1
            try:
                result = await engine(
                    url, platform, output_dir, progress_callback, quality, owner_id
                )
                self.engine_metrics[metric_key]["successes"] += 1
                return result
            except DownloadError as exc:
                last_error = exc
                self.engine_metrics[metric_key]["failures"] += 1
                self.last_engine_error = str(exc)[:200]
                if (
                    attempt >= self.engine_attempts
                    or not self._is_retryable_error(exc)
                    or (owner_id is not None and owner_id in self.cancel_requested)
                ):
                    break
                delay = self.retry_base_delay * (2 ** (attempt - 1))
                logger.info(
                    "Retrying %s after attempt %s/%s in %ss",
                    metric_key, attempt, self.engine_attempts, delay,
                )
                if delay:
                    await asyncio.sleep(delay)
        raise last_error or DownloadError("Download engine failed")

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        value = str(error).lower()
        permanent = (
            "canceled", "private", "requires login", "authentication",
            "unavailable or deleted", "unavailable or expired", "unsupported",
            "larger than", "invalid",
        )
        return not any(token in value for token in permanent)

    def diagnostics(self) -> dict[str, object]:
        return {
            "workers_alive": sum(not task.done() for task in self.worker_tasks),
            "workers_expected": self.worker_count,
            "queued": self.queue.qsize(),
            "active": len(self.active_processes),
            "instagram_authenticated": self.instagram_cookies_file is not None,
            "engines": {name: dict(values) for name, values in self.engine_metrics.items()},
            "last_error": self.last_engine_error,
        }

    async def _download_ytdlp(
        self,
        url: str,
        platform: Platform,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        quality: str = "best",
        owner_id: int | None = None,
    ) -> DownloadResult:
        if owner_id is not None and owner_id in self.cancel_requested:
            raise DownloadError("Download canceled")
        job_dir = Path(tempfile.mkdtemp(prefix="download-", dir=self.temp_root))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(job_dir / "%(id)s.%(ext)s")
        height = {"small": 480, "balanced": 720}.get(quality)
        if platform == Platform.INSTAGRAM:
            format_selector = (
                f"best[height<={height}][ext=mp4]/best[ext=mp4]/best"
                if height else "best[ext=mp4]/best"
            )
        else:
            format_selector = (
                f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
                f"b[height<={height}][ext=mp4]/b"
                if height else "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"
            )
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-playlist",
            "--restrict-filenames",
            "--no-warnings",
            "--no-update",
            "--newline",
            "--socket-timeout",
            "20",
            "--extractor-retries",
            "3",
            "--fragment-retries",
            "5",
            "--file-access-retries",
            "3",
            "--retry-sleep",
            "exponential:1:8",
            "--retry-all-errors",
            "--retries",
            "3",
            "--max-filesize",
            str(self.max_file_size_bytes),
            "-f",
            format_selector,
            "--merge-output-format",
            "mp4",
            "--print",
            "after_move:__BOT_PATH__=%(filepath)s",
            "--print",
            "before_download:__BOT_META__=%(title)s|%(duration)s",
            "-o",
            output_template,
            url,
        ]
        if platform == Platform.INSTAGRAM:
            command[3:3] = [
                "--extractor-args",
                "instagram:app_id=web",
                "--user-agent",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
                "--referer",
                "https://www.instagram.com/",
                "--impersonate",
                "chrome",
            ]
            if self.instagram_cookies_file is not None:
                command[3:3] = ["--cookies", str(self.instagram_cookies_file)]
        logger.info("Starting %s download", platform.value)
        try:
            async with self.semaphore:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                if owner_id is not None:
                    self.active_processes[owner_id] = process
                stderr_task = asyncio.create_task(process.stderr.read())  # type: ignore[union-attr]
                stdout_lines: list[str] = []
                deadline = time.monotonic() + self.timeout_seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    raw_line = await asyncio.wait_for(
                        process.stdout.readline(), timeout=remaining  # type: ignore[union-attr]
                    )
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                    stdout_lines.append(line)
                    match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
                    if match and progress_callback is not None:
                        await progress_callback(int(float(match.group(1))), None)
                await process.wait()
                stderr = await stderr_task
                if owner_id is not None and owner_id in self.cancel_requested:
                    raise DownloadError("Download canceled")
            output = "\n".join(stdout_lines)
            source_path = self._read_output_path(
                output, job_dir, allow_fallback=process.returncode == 0
            )
            if process.returncode != 0 and (source_path is None or not source_path.exists()):
                error_text = stderr.decode("utf-8", errors="replace")[-1200:]
                logger.warning(
                    "yt-dlp failed for %s: %s",
                    platform.value,
                    " ".join(error_text.split())[-800:],
                )
                raise DownloadError(self._friendly_error(error_text))
            if source_path is None or not source_path.exists():
                raise DownloadError("The downloader did not produce a media file")
            if process.returncode != 0:
                logger.warning("yt-dlp returned an error after producing a complete media file")
            size = source_path.stat().st_size
            if size > self.max_file_size_bytes:
                raise DownloadError("The downloaded file is larger than Telegram's configured limit")
            title, duration = self._read_metadata(output)
            destination = output_dir / source_path.name
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(destination))
            info = inspect_media(destination, duration, title)
            return DownloadResult(
                artifacts=(DownloadArtifact(
                    path=info.path, size_bytes=info.size_bytes,
                    duration=info.duration, title=info.title, kind="video",
                ),),
                platform=platform,
            )
        except asyncio.TimeoutError as exc:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            raise DownloadError("Download timed out") from exc
        finally:
            if owner_id is not None:
                self.active_processes.pop(owner_id, None)
            shutil.rmtree(job_dir, ignore_errors=True)

    async def _download_gallery(
        self,
        url: str,
        platform: Platform,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        quality: str = "best",
        owner_id: int | None = None,
    ) -> DownloadResult:
        del quality
        if platform != Platform.INSTAGRAM:
            raise DownloadError("Gallery fallback only supports Instagram")
        if owner_id is not None and owner_id in self.cancel_requested:
            raise DownloadError("Download canceled")
        job_dir = Path(tempfile.mkdtemp(prefix="gallery-", dir=self.temp_root))
        command = [
            sys.executable, "-m", "gallery_dl", "--config-ignore", "--no-mtime",
            "--retries", "4",
            "--filesize-max", str(self.max_file_size_bytes),
            "--range", f"1-{self.max_media_per_post}",
            "--destination", str(job_dir),
        ]
        if self.instagram_cookies_file is not None:
            command.extend(["--cookies", str(self.instagram_cookies_file)])
        command.append(url)
        try:
            async with self.semaphore:
                if progress_callback is not None:
                    await progress_callback(None, "instagram-fallback")
                process = await asyncio.create_subprocess_exec(
                    *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                if owner_id is not None:
                    self.active_processes[owner_id] = process
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=self.timeout_seconds
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    raise DownloadError("Download timed out")
                if owner_id is not None and owner_id in self.cancel_requested:
                    raise DownloadError("Download canceled")
            allowed = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v"}
            files = sorted(
                path for path in job_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in allowed
            )[: self.max_media_per_post]
            if not files:
                detail = stderr.decode("utf-8", errors="replace") or stdout.decode(
                    "utf-8", errors="replace"
                )
                raise DownloadError(self._friendly_error(detail))
            if process.returncode != 0:
                logger.warning(
                    "gallery-dl completed partially; delivering %s valid media item(s)",
                    len(files),
                )

            output_dir.mkdir(parents=True, exist_ok=True)
            artifacts: list[DownloadArtifact] = []
            for index, source in enumerate(files, start=1):
                if source.stat().st_size > self.max_file_size_bytes:
                    raise DownloadError("The file is larger than Telegram's configured limit")
                destination = output_dir / f"instagram_{index:02d}{source.suffix.lower()}"
                shutil.move(str(source), str(destination))
                if destination.suffix.lower() in {".mp4", ".mov", ".m4v"}:
                    info = inspect_media(destination, None, None)
                    artifacts.append(DownloadArtifact(
                        path=info.path, size_bytes=info.size_bytes,
                        duration=info.duration, title=info.title, kind="video",
                    ))
                else:
                    artifacts.append(DownloadArtifact(
                        path=destination, size_bytes=destination.stat().st_size,
                        duration=None, title=None, kind="photo",
                    ))
            if progress_callback is not None:
                await progress_callback(100, "instagram-fallback")
            return DownloadResult(artifacts=tuple(artifacts), platform=platform)
        finally:
            if owner_id is not None:
                self.active_processes.pop(owner_id, None)
            shutil.rmtree(job_dir, ignore_errors=True)

    async def cancel_user(self, user_id: int) -> bool:
        process = self.active_processes.get(user_id)
        self.cancel_requested.add(user_id)
        if process is not None and process.returncode is None:
            process.kill()
        return process is not None or any(owner == user_id for owner in self.in_flight_urls.values())

    def is_cancel_requested(self, user_id: int) -> bool:
        return user_id in self.cancel_requested

    def clear_cancel(self, user_id: int) -> None:
        self.cancel_requested.discard(user_id)

    async def send_progress_from_output(
        self, output: str, callback: ProgressCallback | None
    ) -> None:
        if callback is None:
            return
        match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", output)
        await callback(int(float(match.group(1))) if match else None, None)

    @staticmethod
    def _read_output_path(
        output: str, job_dir: Path, allow_fallback: bool = True
    ) -> Path | None:
        for line in output.splitlines():
            if line.startswith("__BOT_PATH__="):
                candidate = Path(line.removeprefix("__BOT_PATH__=").strip())
                if candidate.is_absolute() and candidate.parent == job_dir:
                    return candidate
        if not allow_fallback:
            return None
        candidates = [p for p in job_dir.iterdir() if p.is_file()]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _read_metadata(output: str) -> tuple[str | None, float | None]:
        for line in output.splitlines():
            if line.startswith("__BOT_META__="):
                raw_title, raw_duration = line.removeprefix("__BOT_META__=").split("|", 1)
                try:
                    duration = float(raw_duration) if raw_duration != "NA" else None
                except ValueError:
                    duration = None
                return raw_title or None, duration
        return None, None

    @staticmethod
    def _friendly_error(stderr: str) -> str:
        lowered = stderr.lower()
        if "private" in lowered or "login" in lowered or "sign in" in lowered:
            return "Instagram or the source requires login for this request"
        if "authenticationerror" in lowered or "unreachable" in lowered:
            return "Instagram requires authentication for this request"
        if "empty media response" in lowered or "unable to extract" in lowered:
            return "The platform changed or blocked its public media response"
        if "429" in lowered or "too many requests" in lowered or "rate limit" in lowered:
            return "The platform is rate-limiting requests; try again shortly"
        if "not available" in lowered or "removed" in lowered or "deleted" in lowered:
            return "This content is unavailable or deleted"
        if "notfound" in lowered or "404" in lowered:
            return "This content is unavailable or expired"
        if "unsupported url" in lowered:
            return "This link format is not supported"
        if "file is larger" in lowered or "max-filesize" in lowered:
            return "The file is larger than Telegram's configured limit"
        if "ffmpeg" in lowered:
            return "Media processing failed"
        return "The platform could not provide this content right now"
