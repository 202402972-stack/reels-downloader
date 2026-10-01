from __future__ import annotations

from datetime import datetime

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...services.validator import Platform
from ..context import AppContext
from ..keyboards.main import back_keyboard, main_keyboard
from ..keyboards.settings import settings_keyboard
from .download import start_batch_download, start_download
from .help import send_help, send_history

router = Router(name="callbacks")


@router.callback_query()
async def callback_handler(
    query: CallbackQuery, context: AppContext, state: FSMContext
) -> None:
    if query.from_user is None:
        return
    user = await context.users.get_user(query.from_user.id)
    language = user.language if user else context.settings.default_language
    await query.answer()
    data = query.data or ""
    if data.startswith("quality:"):
        if data == "quality:cancel":
            await query.message.edit_text(  # type: ignore[union-attr]
                context.translator.get("home", language),
                reply_markup=main_keyboard(language),
            )
            return
        quality = data.removeprefix("quality:")
        if quality not in {"best", "balanced", "small"}:
            return
        stored = await state.get_data()
        raw_items = stored.get("urls")
        if isinstance(raw_items, list) and len(raw_items) > 1:
            items = []
            for item in raw_items:
                if isinstance(item, dict) and item.get("platform") in {"tiktok", "instagram"}:
                    from ...services.validator import ValidatedUrl
                    items.append(ValidatedUrl(str(item.get("url")), Platform(item["platform"])))
            if items:
                await state.update_data(quality=quality)
                await start_batch_download(
                    query.message, context, state, quality, items, language, query.from_user.id  # type: ignore[arg-type,union-attr]
                )
                return
        url = stored.get("url")
        platform_name = stored.get("platform")
        if not isinstance(url, str) or platform_name not in {"tiktok", "instagram"}:
            await query.message.edit_text(context.translator.get("invalid_url", language))  # type: ignore[union-attr]
            return
        await state.update_data(quality=quality)
        await start_download(
            query.message, context, state, quality, url,
            Platform(platform_name), language, query.from_user.id,  # type: ignore[union-attr]
        )
        return
    if data == "download:cancel":
        await state.clear()
        if await context.downloader.cancel_user(query.from_user.id):
            await query.message.edit_text("تم إلغاء التحميل." if language == "ar" else "Download canceled.")  # type: ignore[union-attr]
        else:
            await query.answer("لا يوجد تحميل نشط" if language == "ar" else "No active download", show_alert=True)
        return
    if data == "download:retry":
        stored = await state.get_data()
        url = stored.get("url")
        platform_name = stored.get("platform")
        quality = stored.get("quality", "best")
        if isinstance(url, str) and platform_name in {"tiktok", "instagram"}:
            await start_download(
                query.message, context, state, quality, url,
                Platform(platform_name), language, query.from_user.id,  # type: ignore[union-attr]
            )
        else:
            await query.answer("لا توجد عملية لإعادتها" if language == "ar" else "Nothing to retry", show_alert=True)
        return
    if data == "home":
        await query.message.edit_text(  # type: ignore[union-attr]
            context.translator.get("home", language),
            reply_markup=main_keyboard(language),
        )
    elif data == "download":
        await query.message.edit_text(  # type: ignore[union-attr]
            context.translator.get("send_link", language),
            reply_markup=back_keyboard(language),
        )
    elif data == "batch":
        await query.message.edit_text(  # type: ignore[union-attr]
            context.translator.get("batch.prompt", language, max=context.settings.max_batch_size),
            reply_markup=back_keyboard(language),
        )
    elif data == "help":
        await send_help(query, context, language)
    elif data == "stats":
        stats = await context.users.stats_for_user(query.from_user.id)
        joined = stats["joined"]
        joined_text = (
            joined.strftime("%d %b %Y") if isinstance(joined, datetime) else "—"
        )
        await query.message.edit_text(  # type: ignore[union-attr]
            context.translator.get(
                "stats",
                language,
                total=stats["total"],
                tiktok=stats["tiktok"],
                instagram=stats["instagram"],
                joined=joined_text,
            ),
            reply_markup=back_keyboard(language),
        )
    elif data == "history":
        await send_history(query, context, language)
    elif data == "settings":
        auto_delete = await context.users.get_auto_delete(query.from_user.id)
        await query.message.edit_text(  # type: ignore[union-attr]
            context.translator.get("settings", language),
            reply_markup=settings_keyboard(language, auto_delete),
        )
    elif data.startswith("lang:"):
        new_language = data.removeprefix("lang:")
        if new_language in {"ar", "en"}:
            await context.users.set_language(query.from_user.id, new_language)
            await query.message.edit_text(  # type: ignore[union-attr]
                context.translator.get("settings", new_language),
                reply_markup=settings_keyboard(
                    new_language, await context.users.get_auto_delete(query.from_user.id)
                ),
            )
    elif data == "toggle_delete":
        current = await context.users.get_auto_delete(query.from_user.id)
        await context.users.set_auto_delete(query.from_user.id, not current)
        await query.message.edit_text(  # type: ignore[union-attr]
            context.translator.get("settings", language),
            reply_markup=settings_keyboard(language, not current),
        )
