import asyncio
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler
)
import nest_asyncio # Import nest_asyncio

from core.logger import get_logger
from database.movies import MovieDatabase
from agents.llm_generator import LLMGenerator
from agents.tmdb_agent import TMDBAgent
from agents.translator import TranslatorAgent
from core.engine import RecommendationEngine
from agents.validator import QueryValidator
from agents.feedback import FeedbackAgent

# Импорт хендлеров
from tg_bot.handlers import (
    start_command,
    help_command,
    recommend_command,
    handle_text_message,
    rate_command,
    feedback_command,
    history_command,
    view_saved_movies_command
)

# Импорт колбэков
from tg_bot.callbacks import (
    save_movie_callback,
    rate_movie_callback,
    select_movie_for_rating,
    get_rating_score,
    show_movie_details_callback,
    more_recommendations_callback,
    cancel_callback,
    confirmation_callback,
    back_callback,
    collect_feedback,
)


# Загрузка .env
load_dotenv()
nest_asyncio.apply() # Apply nest_asyncio to allow nested event loops

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
LLM_API_KEY = os.getenv('OPENROUTER_API_KEY')
TMDB_API_KEY = os.getenv('TMDB_API_KEY')

logger = get_logger("main")

if not TELEGRAM_TOKEN or not LLM_API_KEY or not TMDB_API_KEY:
    logger.error("❌ Не найдены все необходимые ключи API в .env")
    exit(1)


async def main():
    logger.info("🚀 Запуск Telegram-бота...")

    # Инициализация компонентов
    db = MovieDatabase("data/movie_recommendations.db")
    llm = LLMGenerator(api_key=LLM_API_KEY)
    tmdb = TMDBAgent(api_key=TMDB_API_KEY)
    translator = TranslatorAgent(llm_generator=llm)
    engine = RecommendationEngine(
        llm_generator=llm,
        tmdb_agent=tmdb,
        db=db,
        translator_agent=translator
    )
    query_validator = QueryValidator()
    feedback_agent = FeedbackAgent("data/movie_feedback.db")


    # Telegram приложение
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Проброс зависимостей в context.bot_data
    app.bot_data["db"] = db
    app.bot_data["llm_generator"] = llm
    app.bot_data["tmdb_agent"] = tmdb
    app.bot_data["translator_agent"] = translator
    app.bot_data["recommendation_engine"] = engine
    app.bot_data["query_validator"] = query_validator
    app.bot_data["feedback_agent"] = feedback_agent
    app.bot_data["logger"] = logger

    # Определения состояний для ConversationHandler'ов
    RECOMMENDATION_STATE = 0
    RATING_SELECT_MOVIE = 1
    RATING_GET_SCORE = 2
    FEEDBACK_COLLECTING = 3


    # ConversationHandler для оценки фильмов
    rating_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("rate", rate_command),
            CallbackQueryHandler(select_movie_for_rating, pattern=r'^select_movie_for_rating_\d+$')
        ],
        states={
            RATING_SELECT_MOVIE: [
                CallbackQueryHandler(select_movie_for_rating, pattern=r'^select_movie_for_rating_\d+$')
            ],
            RATING_GET_SCORE: [
                CallbackQueryHandler(get_rating_score, pattern=r'^rate:\d+:(?:[0-9]|10)$')
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_callback),
            CallbackQueryHandler(cancel_callback, pattern='^cancel$')
        ],
        allow_reentry=True
    )

    # ConversationHandler для обратной связи
    feedback_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("feedback", feedback_command),
            CallbackQueryHandler(feedback_command, pattern='^start_feedback$')
        ],
        states={
            FEEDBACK_COLLECTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_feedback)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_callback),
            CallbackQueryHandler(cancel_callback, pattern='^cancel$')
        ],
        allow_reentry=True
    )

    # Регистрация хендлеров
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("recommend", recommend_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CallbackQueryHandler(view_saved_movies_command, pattern='^view_saved_movies$'))

    # Добавляем ConversationHandler'ы
    app.add_handler(rating_conv_handler)
    app.add_handler(feedback_conv_handler)

    # Регистрация колбэк-запросов, не относящихся к ConversationHandler напрямую
    app.add_handler(CallbackQueryHandler(save_movie_callback, pattern='^save:\\d+$'))
    app.add_handler(CallbackQueryHandler(rate_movie_callback, pattern=r'^rate:\d+:(?:[0-9]|10)$'))
    app.add_handler(CallbackQueryHandler(show_movie_details_callback, pattern='^details:\\d+$'))
    app.add_handler(CallbackQueryHandler(more_recommendations_callback, pattern='^get_recommendations$'))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern='^cancel$'))
    app.add_handler(CallbackQueryHandler(confirmation_callback, pattern='^confirm:.+$'))
    app.add_handler(CallbackQueryHandler(back_callback, pattern='^back:.+$'))
    app.add_handler(CallbackQueryHandler(feedback_command, pattern='^start_feedback$'))


    logger.info("✅ Бот успешно запущен. Ожидаем входящие сообщения...")

    await app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Fatal error during bot startup: {e}", exc_info=True)

