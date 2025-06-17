# tg_bot/keyboards.py
from typing import List, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.logger import get_logger

logger = get_logger("keyboards")


def get_start_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура для стартового меню с основными действиями.
    Убраны "Настройки" и упрощено главное меню.
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("🎬 Получить рекомендации", callback_data="get_recommendations"),
        ],
        [
            InlineKeyboardButton("❤️ Сохраненные фильмы", callback_data="view_saved_movies"),
            InlineKeyboardButton("📜 История", callback_data="view_history"),
        ],
        [
            InlineKeyboardButton("✍️ Оставить отзыв", callback_data="start_feedback"),
        ]
    ])
    logger.info("Сформирована стартовая клавиатура.")
    return keyboard


def get_rating_keyboard(movie_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для оценки фильма (от 0 до 10).
    Кнопки расположены в два ряда для лучшей читаемости.
    """
    rating_buttons = []
    # Добавляем кнопку 0
    rating_buttons.append(InlineKeyboardButton("0", callback_data=f"rate:{movie_id}:0"))

    # Добавляем кнопки от 1 до 10
    for i in range(1, 11):
        rating_buttons.append(InlineKeyboardButton(str(i), callback_data=f"rate:{movie_id}:{i}"))

    # Разделяем на два ряда: 0-5 и 6-10 (6 кнопок в каждом ряду)
    # Если список кнопок не делится ровно, последний ряд будет содержать оставшиеся кнопки
    rows = []
    # Первая строка: 0-5
    if len(rating_buttons) >= 6:
        rows.append(rating_buttons[0:6])
        # Вторая строка: 6-10
        rows.append(rating_buttons[6:11])
    else:  # Если вдруг меньше 11 кнопок (не должно быть, но для надежности)
        rows.append(rating_buttons)

    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    logger.info(f"Сформирована клавиатура оценки для фильма ID: {movie_id} (0-10).")
    return keyboard


def get_confirmation_keyboard(action: str, payload: str = "") -> InlineKeyboardMarkup:
    """
    Клавиатура для подтверждения действия (Да/Нет).
    Args:
        action (str): Тип действия, которое нужно подтвердить (например, 'clear_history', 'clear_prefs').
        payload (str): Дополнительные данные, если требуются для действия.
    """
    callback_data_yes = f"confirm:{action}:{payload}"
    callback_data_no = "cancel"  # Используем общий 'cancel' для отмены

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("✅ Да", callback_data=callback_data_yes),
            InlineKeyboardButton("❌ Нет", callback_data=callback_data_no)
        ]
    ])
    logger.info(f"Сформирована клавиатура подтверждения для действия: {action}.")
    return keyboard


def get_post_action_keyboard(context_type: str = "main_menu") -> InlineKeyboardMarkup:
    """
    Клавиатура, предлагающая действия после выполнения команды.
    Используется вместо ReplyKeyboardRemove.
    Убраны "Настройки", "Главное меню" переименовано в "Больше опций".
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("🎬 Ещё рекомендации", callback_data="get_recommendations"),
            InlineKeyboardButton("❤️ Сохраненные", callback_data="view_saved_movies"),
        ],
        [
            InlineKeyboardButton("📜 История", callback_data="view_history"),
            InlineKeyboardButton("✍️ Отзыв", callback_data="start_feedback")
        ]
    ])
    logger.info(f"Сформирована клавиатура 'post_action' для контекста: {context_type}.")
    return keyboard


def get_back_keyboard(target: str = "main_menu") -> InlineKeyboardMarkup:
    """
    Клавиатура с кнопкой '🔙 Назад'.

    Args:
        target (str): Целевое место, куда должна вернуть кнопка 'Назад' (например, 'main_menu', 'preferences').
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔙 Назад", callback_data=f"back:{target}")]
    ])
    logger.info(f"Сформирована клавиатура 'Назад' с целью: {target}.")
    return keyboard

