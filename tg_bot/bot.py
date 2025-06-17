from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters
from telegram import Update
from core.logger import get_logger
from typing import Callable, Dict, Any

# Импортируем состояния из main.py, если они там определены или
# если мы их перенесем в отдельный файл состояний (что было бы лучше для большого проекта)
# Для простоты, пока будем предполагать, что они доступны, или вы их определите тут же,
# либо передадите в функцию. В нашем случае они используются в main.py, поэтому
# логичнее будет перенести сюда только регистрацию, а ConversationHandler'ы останутся в main.py
# или будут переданы извне.
# Но если все обработчики, включая ConversationHandler, будут здесь, то нужно будет определить STATES здесь.

logger = get_logger("telegram_bot_app")

# Вспомогательная функция для регистрации обработчиков
def register_all_handlers(application: Application):
    """
    Регистрирует все команды, текстовые обработчики и обработчики колбэков
    в экземпляре Telegram Application.

    Args:
        application: Экземпляр telegram.ext.Application.
    """
    # Здесь должны быть импорты ваших конкретных функций-обработчиков
    # Например, из tg_bot.handlers и tg_bot.callbacks
    # Для демонстрации я использую те, что были в main.py:
    from main import (
        start, help_command, recommend_command, history_command,
        handle_text_message,
        rating_conv_handler, feedback_conv_handler, preferences_conv_handler # Импортируем ConversationHandler'ы
    )

    logger.info("Регистрация стандартных обработчиков...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("recommend", recommend_command))
    application.add_handler(CommandHandler("history", history_command))

    logger.info("Регистрация основного обработчика текстовых сообщений...")
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("Регистрация ConversationHandler'ов...")
    application.add_handler(rating_conv_handler)
    application.add_handler(feedback_conv_handler)
    application.add_handler(preferences_conv_handler)

    # Дополнительные обработчики, если есть:
    # application.add_handler(CallbackQueryHandler(your_callback_handler_function, pattern="^your_pattern$"))
    # ...

    logger.info("Все обработчики зарегистрированы.")


def build_telegram_application(token: str) -> Application:
    """
    Создает, настраивает и возвращает экземпляр Telegram Application.

    Args:
        token (str): Токен вашего Telegram-бота.

    Returns:
        Application: Готовый к запуску экземпляр Telegram Application.
    """
    logger.info("Начало сборки Telegram Application...")
    application = Application.builder().token(token).build()

    # Регистрируем все обработчики
    register_all_handlers(application)

    logger.info("Telegram Application успешно собрано.")
    return application

