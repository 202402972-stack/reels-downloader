from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from html import escape

from ..context import AppContext
from ..keyboards.main import main_keyboard

router = Router(name="start")


@router.message(CommandStart())
async def start_handler(message: Message, context: AppContext) -> None:
    user = message.from_user
    if user is None:
        return
    saved = await context.users.upsert_user(
        user.id,
        user.username,
        user.first_name,
        context.settings.default_language,
    )
    language = saved.language
    if saved.is_blocked:
        await message.answer(context.translator.get("blocked", language))
        return
    await message.answer(
        context.translator.get("welcome", language, name=escape(user.first_name)),
        reply_markup=main_keyboard(language),
    )


@router.message(Command("download"))
async def download_command(message: Message, context: AppContext) -> None:
    user = message.from_user
    language = context.settings.default_language
    if user is not None:
        saved = await context.users.get_user(user.id)
        language = saved.language if saved else language
    await message.answer(
        context.translator.get("send_link", language),
        reply_markup=main_keyboard(language),
    )