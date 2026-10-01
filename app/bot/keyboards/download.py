from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def quality_keyboard(language: str) -> InlineKeyboardMarkup:
    labels = (
        ("أفضل جودة", "Best quality"),
        ("متوازنة (حتى 720p)", "Balanced (up to 720p)"),
        ("حجم صغير (حتى 480p)", "Small (up to 480p)"),
    )
    index = 0 if language == "ar" else 1
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=labels[0][index], callback_data="quality:best")],
            [InlineKeyboardButton(text=labels[1][index], callback_data="quality:balanced")],
            [InlineKeyboardButton(text=labels[2][index], callback_data="quality:small")],
            [InlineKeyboardButton(
                text="إلغاء" if language == "ar" else "Cancel",
                callback_data="quality:cancel",
            )],
        ]
    )


def cancel_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="إلغاء التحميل" if language == "ar" else "Cancel download",
            callback_data="download:cancel",
        )
    ]])


def batch_cancel_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="إلغاء الدفعة بالكامل" if language == "ar" else "Cancel entire batch",
            callback_data="download:cancel",
        )
    ]])


def retry_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="إعادة المحاولة" if language == "ar" else "Retry",
            callback_data="download:retry",
        )
    ]])


def share_keyboard(url: str, language: str) -> InlineKeyboardMarkup:
    share_url = f"https://t.me/share/url?url={quote(url, safe='')}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 مشاركة" if language == "ar" else "🔗 Share",
                    url=share_url,
                )
            ]
        ]
    )
