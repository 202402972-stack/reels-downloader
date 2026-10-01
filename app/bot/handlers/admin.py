from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError, TelegramRetryAfter

from ...services.cleanup import cleanup_old_files
from ..context import AppContext
from ..keyboards.admin import admin_keyboard
from ..keyboards.main import back_keyboard

logger = logging.getLogger(__name__)
router = Router(name="admin")


class AdminInput(StatesGroup):
    broadcast_message = State()
    user_id = State()


def is_admin(user_id: int, context: AppContext) -> bool:
    return user_id in context.settings.admin_ids


@router.message(Command("admin"))
async def admin_command(message: Message, context: AppContext) -> None:
    if message.from_user is None:
        return
    language = context.settings.default_language
    if not context.settings.admin_ids:
        await message.answer(context.translator.get("admin.not_configured", language))
        logger.warning("Admin command received but ADMIN_IDS is not configured")
        return
    if not is_admin(message.from_user.id, context):
        await message.answer(context.translator.get("admin.unauthorized", language))
        return
    await message.answer(
        context.translator.get("admin.title", language),
        reply_markup=admin_keyboard(language),
    )


@router.message(Command("id"))
async def user_id_command(message: Message, context: AppContext) -> None:
    if message.from_user is None:
        return
    await message.answer(
        context.translator.get(
            "admin.your_id", context.settings.default_language, user_id=message.from_user.id
        )
    )


@router.callback_query(lambda query: (query.data or "").startswith("admin:"))
async def admin_callback(
    query: CallbackQuery, context: AppContext, state: FSMContext
) -> None:
    if not is_admin(query.from_user.id, context):
        await query.answer("Not authorized", show_alert=True)
        return
    await query.answer()
    action = (query.data or "").removeprefix("admin:")
    language = context.settings.default_language
    if action == "stats":
        stats = await context.users.global_stats()
        text = context.translator.get("admin.stats", language, **stats)
    elif action == "clean":
        count = 0
        for directory in ("temp", "downloads"):
            count += await asyncio.to_thread(
                cleanup_old_files,
                context.settings.root_dir / directory,
                context.settings.temp_retention_minutes * 60,
            )
        text = context.translator.get("admin.cleaned", language, count=count)
    elif action == "users":
        stats = await context.users.global_stats()
        text = context.translator.get("admin.users", language, **stats)
    elif action == "downloads":
        stats = await context.users.global_stats()
        text = context.translator.get("admin.downloads", language, **stats)
    elif action == "health":
        stats = await context.users.global_stats()
        diagnostics = context.downloader.diagnostics()
        engines = diagnostics["engines"]
        yt = engines["yt_dlp"]  # type: ignore[index]
        gallery = engines["gallery_dl"]  # type: ignore[index]
        text = context.translator.get(
            "admin.health",
            language,
            queued=diagnostics["queued"],
            active=diagnostics["active"],
            workers=f"{diagnostics['workers_alive']}/{diagnostics['workers_expected']}",
            auth=("مفعّلة" if diagnostics["instagram_authenticated"] else "غير مفعّلة")
            if language == "ar" else
            ("Enabled" if diagnostics["instagram_authenticated"] else "Disabled"),
            yt=f"{yt['successes']}/{yt['attempts']}",  # type: ignore[index]
            gallery=f"{gallery['successes']}/{gallery['attempts']}",  # type: ignore[index]
            users=stats["total_users"],
            failed=stats["failed_downloads"],
        )
    elif action in {"block", "unblock"}:
        await state.set_state(AdminInput.user_id)
        await state.update_data(block=action == "block")
        await query.message.edit_text(  # type: ignore[union-attr]
            context.translator.get("admin.ask_user_id", language),
            reply_markup=back_keyboard(language),
        )
        return
    elif action == "broadcast":
        await state.set_state(AdminInput.broadcast_message)
        await query.message.edit_text(  # type: ignore[union-attr]
            context.translator.get("admin.ask_broadcast", language),
            reply_markup=back_keyboard(language),
        )
        return
    else:
        text = context.translator.get("admin.coming_soon", language)
    await query.message.edit_text(text, reply_markup=back_keyboard(language))  # type: ignore[union-attr]


async def broadcast(message: Message, context: AppContext, text: str) -> tuple[int, int, int]:
    sent = failed = blocked = 0
    text = text[:4000]
    for user_id in await context.users.all_user_ids():
        try:
            await message.bot.send_message(user_id, text, parse_mode=None)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1
            await context.users.mark_blocked(user_id, True)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await message.bot.send_message(user_id, text, parse_mode=None)
                sent += 1
            except TelegramForbiddenError:
                blocked += 1
                await context.users.mark_blocked(user_id, True)
            except TelegramAPIError:
                failed += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(0.05)
    return sent, failed, blocked


@router.message(AdminInput.user_id)
async def admin_user_action(message: Message, context: AppContext, state: FSMContext) -> None:
    if not message.from_user or not is_admin(message.from_user.id, context):
        await state.clear()
        return
    try:
        user_id = int((message.text or "").strip())
    except ValueError:
        await message.answer(context.translator.get("admin.invalid_user_id", "ar"))
        return
    data = await state.get_data()
    await context.users.mark_blocked(user_id, bool(data.get("block")))
    await state.clear()
    key = "admin.blocked" if data.get("block") else "admin.unblocked"
    await message.answer(context.translator.get(key, context.settings.default_language, user_id=user_id))


@router.message(AdminInput.broadcast_message)
async def admin_broadcast_message(
    message: Message, context: AppContext, state: FSMContext
) -> None:
    if not message.from_user or not is_admin(message.from_user.id, context):
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        return
    await state.clear()
    sent, failed, blocked = await broadcast(message, context, text)
    await message.answer(
        context.translator.get(
            "admin.broadcast_result",
            context.settings.default_language,
            sent=sent,
            failed=failed,
            blocked=blocked,
        )
    )
