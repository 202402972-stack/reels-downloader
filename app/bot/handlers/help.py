from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..context import AppContext
from ..keyboards.main import back_keyboard

router = Router(name="help")


@router.message(Command("help"))
async def help_handler(message: Message, context: AppContext) -> None:
    user = message.from_user
    language = context.settings.default_language
    if user is not None:
        saved = await context.users.get_user(user.id)
        language = saved.language if saved else language
    await send_help(message, context, language)


@router.message(Command("stats"))
async def stats_command(message: Message, context: AppContext) -> None:
    user = message.from_user
    if user is None:
        return
    saved = await context.users.get_user(user.id)
    language = saved.language if saved else context.settings.default_language
    stats = await context.users.stats_for_user(user.id)
    joined = stats["joined"]
    joined_text = joined.strftime("%d %b %Y") if isinstance(joined, datetime) else "—"
    await message.answer(
        context.translator.get(
            "stats", language, total=stats["total"], tiktok=stats["tiktok"],
            instagram=stats["instagram"], joined=joined_text,
        ),
        reply_markup=back_keyboard(language),
    )


@router.message(Command("settings"))
async def settings_command(message: Message, context: AppContext) -> None:
    user = message.from_user
    if user is None:
        return
    saved = await context.users.get_user(user.id)
    language = saved.language if saved else context.settings.default_language
    from ..keyboards.settings import settings_keyboard
    await message.answer(
        context.translator.get("settings", language),
        reply_markup=settings_keyboard(language, await context.users.get_auto_delete(user.id)),
    )


async def send_history(
    target: Message | CallbackQuery, context: AppContext, language: str
) -> None:
    user = target.from_user
    if user is None:
        return
    items = await context.users.recent_downloads(user.id)
    if not items:
        text = context.translator.get("history_empty", language)
    else:
        lines = []
        for item in items:
            platform = str(item["platform"]).title()
            status = context.translator.get(f"status.{item['status']}", language)
            created = str(item["created_at"])[:16].replace("T", " ")
            lines.append(f"• <b>{platform}</b> — {status}\n  {created}")
        text = context.translator.get("history", language, items="\n".join(lines))
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=back_keyboard(language))  # type: ignore[union-attr]
    else:
        await target.answer(text, reply_markup=back_keyboard(language))


@router.message(Command("history"))
async def history_command(message: Message, context: AppContext) -> None:
    user = message.from_user
    language = context.settings.default_language
    if user is not None:
        saved = await context.users.get_user(user.id)
        language = saved.language if saved else language
    await send_history(message, context, language)


@router.message(Command("privacy"))
async def privacy_command(message: Message, context: AppContext) -> None:
    user = message.from_user
    language = context.settings.default_language
    if user is not None:
        saved = await context.users.get_user(user.id)
        language = saved.language if saved else language
    await message.answer(
        context.translator.get("privacy", language),
        reply_markup=back_keyboard(language),
    )


@router.message(Command("batch"))
async def batch_command(message: Message, context: AppContext) -> None:
    user = message.from_user
    language = context.settings.default_language
    if user is not None:
        saved = await context.users.get_user(user.id)
        language = saved.language if saved else language
    await message.answer(
        context.translator.get("batch.prompt", language, max=context.settings.max_batch_size),
        reply_markup=back_keyboard(language),
    )


async def send_help(target: Message | CallbackQuery, context: AppContext, language: str) -> None:
    text = context.translator.get("help", language)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=back_keyboard(language))  # type: ignore[union-attr]
    else:
        await target.answer(text, reply_markup=back_keyboard(language))
