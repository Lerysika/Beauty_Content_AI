"""Reply-клавиатуры для Telegram-бота."""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Возвращает Reply Keyboard с кнопкой главного меню.
    
    Клавиатура содержит одну кнопку для возврата в главное меню.
    Используется resize_keyboard=True для компактности.
    
    Returns:
        ReplyKeyboardMarkup с кнопкой "🏠 Главное меню"
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )
