from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def settings_keyboard(language: str, auto_delete: bool) -> InlineKeyboardMarkup:
    auto_delete_text = (
        ("الحذف التلقائي: مفعّل" if auto_delete else "الحذف التلقائي: متوقف")
        if language == "ar"
        else ("Auto-delete: On" if auto_delete else "Auto-delete: Off")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇪🇬 العربية", callback_data="lang:ar"),
                InlineKeyboardButton(text="🇺🇸 English", callback_data="lang:en"),
            ],
            [InlineKeyboardButton(text=f"🗑️ {auto_delete_text}", callback_data="toggle_delete")],
            [
                InlineKeyboardButton(
                    text="رجوع" if language == "ar" else "Back", callback_data="home"
                )
            ],
        ]
    )