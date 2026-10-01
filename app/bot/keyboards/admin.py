from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_keyboard(language: str = "ar") -> InlineKeyboardMarkup:
    labels = (
        ("المستخدمون", "Users"),
        ("التحميلات", "Downloads"),
        ("الإحصائيات", "Statistics"),
        ("حظر مستخدم", "Block user"),
        ("إلغاء حظر", "Unblock user"),
        ("Broadcast", "Broadcast"),
        ("تنظيف الملفات", "Clean files"),
        ("صحة النظام", "System health"),
    )
    lang_index = 0 if language == "ar" else 1
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"👥 {labels[0][lang_index]}", callback_data="admin:users")],
            [
                InlineKeyboardButton(text=f"📥 {labels[1][lang_index]}", callback_data="admin:downloads"),
                InlineKeyboardButton(text=f"📊 {labels[2][lang_index]}", callback_data="admin:stats"),
            ],
            [
                InlineKeyboardButton(text=f"🚫 {labels[3][lang_index]}", callback_data="admin:block"),
                InlineKeyboardButton(text=f"🔓 {labels[4][lang_index]}", callback_data="admin:unblock"),
            ],
            [InlineKeyboardButton(text=f"📢 {labels[5][lang_index]}", callback_data="admin:broadcast")],
            [InlineKeyboardButton(text=f"🧹 {labels[6][lang_index]}", callback_data="admin:clean")],
            [InlineKeyboardButton(text=f"🩺 {labels[7][lang_index]}", callback_data="admin:health")],
            [InlineKeyboardButton(
                text="🏠 الرئيسية" if language == "ar" else "🏠 Home",
                callback_data="home",
            )],
        ]
    )