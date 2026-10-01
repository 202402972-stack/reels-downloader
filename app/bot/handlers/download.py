from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo, Message

from ...services.cleanup import remove_path
from ...services.downloader import DownloadError, DownloadResult
from ...services.media import format_bytes
from ...services.rate_limiter import RateLimitExceeded
from ...services.validator import Platform, ValidatedUrl, extract_urls, validate_url
from ..context import AppContext
from ..keyboards.download import (
    batch_cancel_keyboard, cancel_keyboard, quality_keyboard, retry_keyboard, share_keyboard,
)
from ..keyboards.main import back_keyboard

logger = logging.getLogger(__name__)
router = Router(name="download")


class DownloadInput(StatesGroup):
    quality = State()


async def _get_language(message: Message, context: AppContext) -> str:
    user = message.from_user
    if user is None:
        return context.settings.default_language
    saved = await context.users.upsert_user(
        user.id, user.username, user.first_name, context.settings.default_language
    )
    if saved.is_blocked:
        return "blocked"
    return saved.language


@router.message()
async def link_handler(message: Message, context: AppContext, state: FSMContext) -> None:
    if not message.text or message.text.startswith("/"):
        return
    language = await _get_language(message, context)
    if language == "blocked":
        await message.answer(context.translator.get("blocked", context.settings.default_language))
        return
    try:
        urls = extract_urls(message.text, context.settings.max_batch_size)
        if not urls:
            validated = validate_url(message.text)
            urls = [validated]
        await context.rate_limiter.check(message.from_user.id)  # type: ignore[union-attr]
    except RateLimitExceeded:
        await message.answer(context.translator.get("rate_limit", language))
        return
    except ValueError:
        await message.answer(context.translator.get("invalid_url", language))
        return

    user_id = message.from_user.id  # type: ignore[union-attr]
    await state.set_state(DownloadInput.quality)
    await state.update_data(
        urls=[{"url": item.url, "platform": item.platform.value} for item in urls],
        url=urls[0].url,
        platform=urls[0].platform.value,
    )
    await message.answer(
        context.translator.get("batch.detected", language, count=len(urls))
        if len(urls) > 1
        else context.translator.get("choose_quality", language),
        reply_markup=quality_keyboard(language),
    )


async def _send_result(
    message: Message, result: DownloadResult, url: str, caption: str, language: str
) -> None:
    if len(result.artifacts) > 1:
        media = []
        for index, artifact in enumerate(result.artifacts):
            kwargs = {"media": FSInputFile(artifact.path)}
            if index == 0:
                kwargs["caption"] = caption
            media.append(
                InputMediaPhoto(**kwargs) if artifact.kind == "photo"
                else InputMediaVideo(**kwargs, supports_streaming=True)
            )
        try:
            await _telegram_send(
                lambda: message.bot.send_media_group(chat_id=message.chat.id, media=media)
            )
            await _telegram_send(
                lambda: message.answer(
                    context_text(language, "source"),
                    reply_markup=share_keyboard(url, language),
                )
            )
            return
        except (TelegramBadRequest, TelegramNetworkError):
            logger.warning("Media-group upload failed; retrying artifacts individually")
            for index, artifact in enumerate(result.artifacts):
                item_caption = caption if index == 0 else None
                markup = share_keyboard(url, language) if index == len(result.artifacts) - 1 else None
                try:
                    if artifact.kind == "photo":
                        await _telegram_send(
                            lambda: message.bot.send_photo(
                                chat_id=message.chat.id, photo=FSInputFile(artifact.path),
                                caption=item_caption, reply_markup=markup,
                            )
                        )
                    else:
                        await _telegram_send(
                            lambda: message.bot.send_video(
                                chat_id=message.chat.id, video=FSInputFile(artifact.path),
                                caption=item_caption, reply_markup=markup, supports_streaming=True,
                            )
                        )
                except (TelegramBadRequest, TelegramNetworkError):
                    await _telegram_send(
                        lambda: message.bot.send_document(
                            chat_id=message.chat.id, document=FSInputFile(artifact.path),
                            caption=item_caption, reply_markup=markup,
                        )
                    )
            return
    artifact = result.artifacts[0]
    try:
        if artifact.kind == "photo":
            await _telegram_send(
                lambda: message.bot.send_photo(
                    chat_id=message.chat.id, photo=FSInputFile(artifact.path), caption=caption,
                    reply_markup=share_keyboard(url, language),
                )
            )
        else:
            await _telegram_send(
                lambda: message.bot.send_video(
                    chat_id=message.chat.id, video=FSInputFile(artifact.path), caption=caption,
                    reply_markup=share_keyboard(url, language), supports_streaming=True,
                )
            )
    except (TelegramBadRequest, TelegramNetworkError):
        await _telegram_send(
            lambda: message.bot.send_document(
                chat_id=message.chat.id, document=FSInputFile(result.path), caption=caption,
                reply_markup=share_keyboard(url, language),
            )
        )


async def _telegram_send(operation, attempts: int = 3):
    """Retry transient Bot API delivery failures without hiding format errors."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except TelegramRetryAfter as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            await asyncio.sleep(float(exc.retry_after) + 0.25)
        except TelegramNetworkError as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            await asyncio.sleep(2 ** (attempt - 1))
    if last_error is not None:
        raise last_error


def context_text(language: str, key: str) -> str:
    if key == "source":
        return "🔗 رابط المنشور الأصلي" if language == "ar" else "🔗 Original post"
    return key


def _error_key(exc: Exception) -> str:
    value = str(exc).lower()
    if "canceled" in value:
        return "download_canceled"
    if "requires login" in value:
        return "download_access"
    if "rate-limit" in value or "rate limiting" in value:
        return "download_rate_limited"
    if "changed or blocked" in value:
        return "download_unavailable"
    return "download_failed"


async def start_batch_download(
    message: Message, context: AppContext, state: FSMContext, quality: str,
    items: list[ValidatedUrl], language: str, user_id: int,
) -> None:
    urls = [item.url for item in items]
    user_lock, claimed = await context.downloader.claim_many(user_id, urls)
    if not claimed:
        await message.answer(context.translator.get("busy", language))
        return
    output_dir = context.settings.root_dir / "downloads" / str(user_id)
    status = await message.answer(
        context.translator.get("batch.starting", language, count=len(items)),
        reply_markup=batch_cancel_keyboard(language),
    )
    completed = failed = 0
    total_bytes = 0
    try:
        async with user_lock:
            for index, item in enumerate(items, start=1):
                if context.downloader.is_cancel_requested(user_id):
                    break
                download_id = await context.users.create_download(user_id, item.platform.value, item.url)
                last_progress = -1

                async def update_progress(percent: int | None, _detail: str | None) -> None:
                    nonlocal last_progress
                    current = int(percent or 0)
                    if percent is not None and current != 100 and current - last_progress < 10:
                        return
                    last_progress = current
                    filled = min(10, max(0, current // 10))
                    try:
                        await status.edit_text(
                            context.translator.get(
                                "batch.progress", language, index=index, total=len(items),
                                platform=item.platform.value.title(), progress_bar="━" * filled + "╌" * (10 - filled),
                                percent=percent if percent is not None else "…", completed=completed, failed=failed,
                            ),
                            reply_markup=batch_cancel_keyboard(language),
                        )
                    except TelegramBadRequest:
                        pass

                started = time.monotonic()
                try:
                    await context.users.finish_download(download_id, "downloading")
                    service = context.tiktok if item.platform == Platform.TIKTOK else context.instagram
                    result = await service.download(
                        item.url, output_dir, progress_callback=update_progress,
                        quality=quality, owner_id=user_id,
                    )
                    caption = context.translator.get(
                        "batch.item_success", language, index=index, total=len(items),
                        platform=item.platform.value.title(), size=format_bytes(result.size_bytes),
                        seconds=int(time.monotonic() - started), count=result.media_count,
                    )
                    await _send_result(message, result, item.url, caption, language)
                    await context.users.finish_download(download_id, "completed", result.size_bytes, result.duration)
                    completed += 1
                    total_bytes += result.size_bytes
                except DownloadError as exc:
                    await context.users.finish_download(download_id, "failed")
                    if "canceled" in str(exc).lower():
                        break
                    failed += 1
                    logger.warning("Batch item %s/%s failed: %s", index, len(items), exc)
                except Exception:
                    failed += 1
                    await context.users.finish_download(download_id, "failed")
                    logger.exception("Unexpected batch item failure for user %s", user_id)
                finally:
                    if output_dir.exists() and await context.users.get_auto_delete(user_id):
                        await asyncio.to_thread(remove_path, output_dir)
        canceled = context.downloader.is_cancel_requested(user_id)
        await status.edit_text(
            context.translator.get(
                "batch.summary", language, completed=completed, failed=failed,
                skipped=len(items) - completed - failed, size=format_bytes(total_bytes),
                state=context.translator.get("batch.canceled" if canceled else "batch.finished", language),
            ),
            reply_markup=None,
        )
        await state.clear()
    finally:
        context.downloader.clear_cancel(user_id)
        await context.downloader.release_many(urls)


async def start_download(
    message: Message,
    context: AppContext,
    state: FSMContext,
    quality: str,
    url: str,
    platform: Platform,
    language: str,
    user_id: int | None = None,
) -> None:
    user_id = user_id or message.from_user.id  # type: ignore[union-attr]
    user_lock, claimed = await context.downloader.claim(user_id, url)
    if not claimed:
        await message.answer(context.translator.get("duplicate", language))
        return
    if user_lock.locked():
        await context.downloader.release(url)
        await message.answer(context.translator.get("busy", language))
        return

    output_dir = context.settings.root_dir / "downloads" / str(user_id)
    status = await message.answer(
        context.translator.get(
            "loading",
            language,
            platform=platform.value.title(),
            quality=quality,
            queued=context.downloader.queue.qsize(),
        ),
        reply_markup=cancel_keyboard(language),
    )
    last_progress = -1

    async def update_progress(percent: int | None, _detail: str | None) -> None:
        nonlocal last_progress
        if percent is None or percent == 100 or percent - last_progress >= 5:
            last_progress = percent if percent is not None else last_progress
            current = int(percent or 0)
            filled = min(10, max(0, current // 10))
            progress_bar = "━" * filled + "╌" * (10 - filled)
            try:
                await status.edit_text(
                    context.translator.get(
                        "progress",
                        language,
                        percent=percent if percent is not None else "…",
                        progress_bar=progress_bar,
                    )
                )
            except TelegramBadRequest:
                # Telegram can reject an edit when the text is unchanged or
                # the message was removed. Progress must never abort a download.
                logger.debug("Progress message could not be edited", exc_info=True)

    download_id = await context.users.create_download(user_id, platform.value, url)
    started = time.monotonic()
    try:
        async with user_lock:
            await context.users.finish_download(download_id, "downloading")
            service = (
                context.tiktok
                if platform == Platform.TIKTOK
                else context.instagram
            )
            result = await service.download(
                url, output_dir, progress_callback=update_progress,
                quality=quality, owner_id=user_id,
            )
        if any(
            artifact.size_bytes > context.settings.max_file_size_bytes
            for artifact in result.artifacts
        ):
            await context.users.finish_download(download_id, "too_large", result.size_bytes)
            await status.edit_text(context.translator.get("too_large", language))
            return
        caption = context.translator.get(
            "success",
            language,
            platform=platform.value.title(),
            size=format_bytes(result.size_bytes),
            seconds=int(time.monotonic() - started),
            count=result.media_count,
        )
        await _send_result(message, result, url, caption, language)
        await context.users.finish_download(
            download_id, "completed", result.size_bytes, result.duration
        )
        await state.clear()
        await status.delete()
    except DownloadError as exc:
        logger.exception("Download failed for user %s", user_id)
        await context.users.finish_download(download_id, "failed")
        error_key = _error_key(exc)
        await status.edit_text(
            context.translator.get(error_key, language),
            reply_markup=retry_keyboard(language),
        )
    except Exception:
        logger.exception("Unexpected download failure for user %s", user_id)
        await context.users.finish_download(download_id, "failed")
        await status.edit_text(context.translator.get("download_failed", language))
    finally:
        context.downloader.clear_cancel(user_id)
        await context.downloader.release(url)
        if output_dir.exists() and await context.users.get_auto_delete(user_id):
            await asyncio.to_thread(remove_path, output_dir)


@router.message(DownloadInput.quality)
async def quality_text_fallback(message: Message, context: AppContext, state: FSMContext) -> None:
    if message.from_user is not None:
        await message.answer(
            "اختر الجودة من الأزرار أعلاه." if (await _get_language(message, context)) == "ar"
            else "Please choose a quality using the buttons above."
        )


@router.message(Command("cancel"))
async def cancel_handler(message: Message, context: AppContext, state: FSMContext) -> None:
    await state.clear()
    if message.from_user and await context.downloader.cancel_user(message.from_user.id):
        await message.answer("تم إلغاء التحميل." if context.settings.default_language == "ar" else "Download canceled.")
    else:
        await message.answer("لا يوجد تحميل نشط." if context.settings.default_language == "ar" else "No active download.")
