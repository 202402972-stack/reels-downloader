import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


SITE_URL = os.getenv("SITE_URL", "https://reels-landing-zeta.vercel.app/")


def main_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    if language == "en":
        labels = ("Download media", "Batch download", "My stats", "Help", "Settings", "Website")
    else:
        labels = ("تحميل محتوى", "تحميل دفعة", "إحصائياتي", "المساعدة", "الإعدادات", "الموقع الإلكتروني")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✨ {labels[0]}", callback_data="download")],
            [InlineKeyboardButton(text=f"📚 {labels[1]}", callback_data="batch")],
            [
                InlineKeyboardButton(text=f"📈 {labels[2]}", callback_data="stats"),
                InlineKeyboardButton(
                    text="🕘 History" if language == "en" else "🕘 السجل",
                    callback_data="history",
                ),
            ],
            [
                InlineKeyboardButton(text=f"💡 {labels[3]}", callback_data="help"),
                InlineKeyboardButton(text=f"🛠️ {labels[4]}", callback_data="settings"),
            ],
            [InlineKeyboardButton(text=f"🌐 {labels[5]}", url=SITE_URL)],
        ]
    )


def back_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="رجوع" if language == "ar" else "Back", callback_data="home"
                )
            ],
            [InlineKeyboardButton(text="🌐 الموقع الإلكتروني" if language == "ar" else "🌐 Website", url=SITE_URL)],
        ]
    )
