from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🏁 Актуальные турниры"),
        ],
        [
            KeyboardButton(text="🔮 Мои прогнозы"),
            KeyboardButton(text="📊 Моя статистика"),
        ],
        [
            KeyboardButton(text="🏆 Рейтинг клуба"),
            KeyboardButton(text="ℹ️ Правила"),
        ],
    ],
    resize_keyboard=True,
)
