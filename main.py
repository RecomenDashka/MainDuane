import logging
import os
import sys
import asyncio
import re  # Add this import for regex
from typing import Dict, Any, List
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

from database import MovieDatabase
from recommendation import RecommendationEngine

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
TMDB_API_KEY = os.getenv('TMDB_API_KEY')

# States for conversation
RECOMMENDATION, RATING, FEEDBACK = range(3)

# Database setup
db = MovieDatabase('movie_recommendations.db')

# Initialize recommendation engine
engine = RecommendationEngine(
    api_key=GOOGLE_API_KEY,
    tmdb_api_key=TMDB_API_KEY,
    db=db
)


# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the command /start is issued."""
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or "новый пользователь"

    # Add user to database if not exists
    if not db.get_user(user_id):
        db.add_user(user_id, username)

    welcome_message = (
        f"👋 Привет, {username}! Я твой персональный помощник по рекомендации фильмов.\n\n"
        "🎬 Я могу:\n"
        "• Рекомендовать фильмы на основе твоих предпочтений\n"
        "• Искать фильмы по жанрам, режиссерам или настроению\n"
        "• Находить похожие фильмы\n\n"
        "💬 Просто напиши, какой фильм ты хочешь посмотреть, например:\n"
        "• \"Посоветуй фильм как Интерстеллар\"\n"
        "• \"Хочу посмотреть комедию про путешествия во времени\"\n"
        "• \"Что-нибудь с Томом Хэнксом\"\n\n"
        "🔍 Используй /help для получения дополнительной информации."
    )

    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message when the command /help is issued."""
    help_message = (
        "🎬 *Как пользоваться ботом*\n\n"
        "*Основные команды:*\n"
        "• /start - Начать разговор с ботом\n"
        "• /help - Показать это сообщение\n"
        "• /profile - Просмотреть свой профиль и предпочтения\n"
        "• /history - Посмотреть историю рекомендаций\n"
        "• /clear - Очистить историю предпочтений\n\n"

        "*Как получить рекомендации:*\n"
        "Просто напишите свой запрос, например:\n"
        "• \"Посоветуй триллер с неожиданной концовкой\"\n"
        "• \"Ищу фильм о космических путешествиях\"\n"
        "• \"Что-то похожее на Матрицу\"\n\n"

        "*Обратная связь:*\n"
        "После получения рекомендации вы можете оценить фильм, "
        "что поможет мне лучше понимать ваши предпочтения."
    )

    await update.message.reply_text(help_message, parse_mode='Markdown')


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user profile when the command /profile is issued."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if not user:
        await update.message.reply_text("Ваш профиль не найден. Используйте /start для начала.")
        return

    # Get user preferences
    preferences = db.get_user_preferences(user_id)

    # Get user ratings
    ratings = db.get_user_ratings(user_id)

    # Prepare profile message
    profile_message = f"👤 *Ваш профиль*\n\n"

    # Add preferences section
    profile_message += "*Ваши предпочтения:*\n"
    if preferences:
        # Group preferences by type
        pref_by_type = {}
        for pref in preferences:
            pref_type = pref['preference_type']
            if pref_type not in pref_by_type:
                pref_by_type[pref_type] = []
            pref_by_type[pref_type].append(pref['preference_value'])

        # Format each preference type
        for pref_type, values in pref_by_type.items():
            # Escape Markdown in preference values
            escaped_values = [escape_markdown(val) for val in values[:5]]
            profile_message += f"• {escape_markdown(pref_type.capitalize())}: {', '.join(escaped_values)}"
            if len(values) > 5:
                profile_message += f" и еще {len(values) - 5}"
            profile_message += "\n"
    else:
        profile_message += "Пока нет сохраненных предпочтений.\n"

    # Add ratings section
    profile_message += "\n*Ваши оценки фильмов:*\n"
    if ratings:
        for i, rating in enumerate(ratings[:5]):  # Show only 5 most recent ratings
            movie = db.get_movie(rating['movie_id'])
            if movie:
                # Escape movie title
                escaped_title = escape_markdown(movie['title'])
                profile_message += f"• {escaped_title} - {rating['rating']}/10\n"
    else:
        profile_message += "Пока нет оценок фильмов.\n"

    # Add statistics
    total_recommendations = db.get_user_history_count(user_id)
    profile_message += f"\n📊 *Статистика:*\n• Получено рекомендаций: {total_recommendations}\n"

    # Add button to clear preferences
    keyboard = [
        [InlineKeyboardButton("🗑️ Очистить предпочтения", callback_data="clear_preferences")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(profile_message, parse_mode='Markdown', reply_markup=reply_markup)


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user recommendation history when the command /history is issued."""
    user_id = update.effective_user.id

    # Get user history from database
    history = db.get_user_history(user_id)

    if not history:
        await update.message.reply_text("У вас пока нет истории рекомендаций.")
        return

    # Prepare history message
    history_message = "📜 *Ваша история рекомендаций:*\n\n"

    # Group history by timestamp (date)
    from datetime import datetime
    from collections import defaultdict

    history_by_date = defaultdict(list)
    for item in history:
        timestamp = item['timestamp']
        date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
        history_by_date[date].append(item)

    # Format history items by date
    for date, items in sorted(history_by_date.items(), reverse=True):
        formatted_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d %b %Y')
        history_message += f"*{formatted_date}*\n"

        for item in items:
            action_type = item['action_type']
            movie = db.get_movie(item['movie_id'])

            if movie:
                # Escape movie title for Markdown
                escaped_title = escape_markdown(movie['title'])

                if action_type.startswith('rated_'):
                    rating = action_type.split('_')[1]
                    history_message += f"• Оценили \"{escaped_title}\" на {rating}/10\n"
                else:
                    history_message += f"• Получили рекомендацию \"{escaped_title}\"\n"

        history_message += "\n"

    # Add button to clear history
    keyboard = [
        [InlineKeyboardButton("🗑️ Очистить историю", callback_data="clear_history")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(history_message, parse_mode='Markdown', reply_markup=reply_markup)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear user preferences and history when the command /clear is issued."""
    user_id = update.effective_user.id

    # Create confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, очистить всё", callback_data="confirm_clear_all"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_clear")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "⚠️ Вы уверены, что хотите очистить все свои предпочтения и историю рекомендаций? "
        "Это действие нельзя отменить.",
        reply_markup=reply_markup
    )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user messages and generate recommendations."""
    user_id = update.effective_user.id
    user_query = update.message.text

    # Check if user exists, if not add them
    if not db.get_user(user_id):
        username = update.effective_user.username or update.effective_user.first_name or "новый пользователь"
        db.add_user(user_id, username)

    # Send typing action
    await update.message.chat.send_action(action="typing")

    # Let user know we're working on it
    processing_message = await update.message.reply_text(
        "🔍 Обрабатываю ваш запрос и подбираю фильмы...",
        reply_to_message_id=update.message.message_id
    )

    try:
        # Generate recommendations
        recommendation_results = await engine.generate_recommendations(user_query, user_id)

        # Delete processing message
        await processing_message.delete()

        # Check if there was an error
        if 'error' in recommendation_results:
            await update.message.reply_text(
                f"😟 Извините, произошла ошибка при получении рекомендаций: {recommendation_results['error']}"
            )
            return ConversationHandler.END

        # Format the recommendations
        llm_response = recommendation_results.get('llm_response', '')
        recommendations = recommendation_results.get('recommendations', [])

        if not recommendations:
            await update.message.reply_text(
                "😕 Извините, не удалось найти конкретные рекомендации фильмов. "
                "Попробуйте изменить запрос или быть более конкретным."
            )
            return ConversationHandler.END

        # Send main recommendation text
        await update.message.reply_text(llm_response)

        # Store recommendations in context for later use
        context.user_data['recommendations'] = recommendations

        # Send detailed cards for each recommended movie
        for movie in recommendations:
            await send_movie_card(update, context, movie)

        # Store recommendations in user history
        for movie in recommendations:
            tmdb_id = movie.get('tmdb_id')
            # Check if movie exists in db
            existing_movie = db.get_movie_by_tmdb_id(tmdb_id)
            movie_id = existing_movie['id'] if existing_movie else db.add_movie(movie)
            # Add to history
            if movie_id:
                db.add_user_history(user_id, movie_id, 'recommended')

        return RECOMMENDATION

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        await processing_message.delete()
        await update.message.reply_text(
            f"😟 Извините, произошла ошибка при обработке вашего запроса: {str(e)}"
        )
        return ConversationHandler.END


def escape_markdown(text: str) -> str:
    """Escape Markdown special characters to prevent formatting issues in Telegram messages."""
    if not text:
        return ""

    # Сначала экранируем обратные слеши
    text = text.replace('\\', '\\\\')

    # Экранируем только основные специальные символы Markdown для Telegram
    # Убираем точки и дефисы из списка, так как они обычно не нужно экранировать
    special_chars = r'_*[]()~`>#+=|{}'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')

    # Удаляем любые оставшиеся проблемные последовательности Unicode
    # Заменяем последовательности вида "\u1234" на их текстовое представление
    text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: f"U+{m.group(1).upper()}", text)

    return text


async def send_movie_card(update: Update, context: ContextTypes.DEFAULT_TYPE, movie: Dict[str, Any]) -> None:
    """Send a card with movie details."""
    title = movie.get('title', 'Unknown Title')
    original_title = movie.get('original_title', '')
    title_display = f"{title} / {original_title}" if original_title and original_title != title else title

    # Determine the message object to use (for regular messages or callback queries)
    if update.callback_query:
        message = update.callback_query.message
        chat_id = update.callback_query.message.chat_id
    else:
        message = update.message
        chat_id = update.message.chat_id

    # Очистка и нормализация строк от возможных проблем с юникодом
    def clean_text(text):
        if not text:
            return ""
        if isinstance(text, list):
            try:
                return ''.join(str(item) for item in text if item)
            except:
                return ""
        return str(text)

    # Escape Markdown characters in text fields
    title_display = escape_markdown(clean_text(title_display))
    overview = escape_markdown(clean_text(movie.get('overview', 'Описание отсутствует.')))
    release_date = clean_text(movie.get('release_date', 'N/A'))
    vote_average = movie.get('vote_average', 0)

    # Format genres and escape Markdown
    genres = movie.get('genres', [])
    # Проверяем, что жанры - это действительно строки, а не списки символов
    clean_genres = []
    for genre in genres:
        clean_genres.append(clean_text(genre))
    genres_text = escape_markdown(', '.join(filter(None, clean_genres)) if clean_genres else 'Не указаны')

    # Format directors and escape Markdown
    directors = movie.get('directors', [])
    # Проверяем, что режиссеры - это действительно строки, а не списки символов
    clean_directors = []
    for director in directors:
        clean_directors.append(clean_text(director))
    directors_text = escape_markdown(', '.join(filter(None, clean_directors)) if clean_directors else 'Не указан')

    # Format actors and escape Markdown
    actors = movie.get('actors', [])
    # Проверяем, что актеры - это действительно строки, а не списки символов
    clean_actors = []
    for actor in actors:
        clean_actors.append(clean_text(actor))
    actors_text = escape_markdown(', '.join(filter(None, clean_actors[:5])) if clean_actors else 'Не указаны')

    # Format runtime
    runtime = movie.get('runtime', 0)
    runtime_text = f"{runtime} мин." if runtime else 'Не указано'

    # Prepare basic info message - без описания для фото
    photo_caption = (
        f"🎬 *{title_display}*\n\n"
        f"📅 *Год выпуска:* {release_date[:4] if release_date and len(release_date) >= 4 else 'Не указан'}\n"
        f"⭐ *Рейтинг:* {vote_average}/10\n"
        f"⏱️ *Продолжительность:* {runtime_text}\n"
        f"🎭 *Жанр:* {genres_text}\n"
        f"🎬 *Режиссер:* {directors_text}"
    )

    # Полное сообщение с описанием и актерами для текстового сообщения
    full_message = (
        f"🎬 *{title_display}*\n\n"
        f"📅 *Год выпуска:* {release_date[:4] if release_date and len(release_date) >= 4 else 'Не указан'}\n"
        f"⭐ *Рейтинг:* {vote_average}/10\n"
        f"⏱️ *Продолжительность:* {runtime_text}\n"
        f"🎭 *Жанр:* {genres_text}\n"
        f"🎬 *Режиссер:* {directors_text}\n"
        f"👨‍👩‍👧‍👦 *В главных ролях:* {actors_text}\n\n"
        f"📝 *Описание:*\n{overview}"
    )

    # Prepare TMDB link
    tmdb_id = movie.get('tmdb_id')
    tmdb_link = f"https://www.themoviedb.org/movie/{tmdb_id}" if tmdb_id else None

    # Create keyboard with rating buttons and TMDB link
    keyboard = []

    # Add rating buttons
    rating_buttons = []
    for rating in range(1, 11):
        # Add movie_id to callback data
        callback_data = f"rate_{tmdb_id}_{rating}" if tmdb_id else f"rate_none_{rating}"
        rating_buttons.append(InlineKeyboardButton(str(rating), callback_data=callback_data))

    # Split rating buttons into 2 rows
    keyboard.append(rating_buttons[:5])
    keyboard.append(rating_buttons[5:])

    # Add TMDB link and similar movies buttons
    bottom_buttons = []
    if tmdb_link:
        bottom_buttons.append(InlineKeyboardButton("🔗 TMDB", url=tmdb_link))
    bottom_buttons.append(InlineKeyboardButton("🔍 Похожие фильмы", callback_data=f"similar_{tmdb_id}"))
    keyboard.append(bottom_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Get poster URL
    poster_path = movie.get('poster_path')
    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

    # Send photo with caption if poster exists, otherwise just send message
    if poster_url:
        try:
            # Отправляем фото только с базовой информацией (без описания и актеров)
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=poster_url,
                caption=photo_caption,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

            # Отправляем отдельным сообщением информацию об актерах и описание
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"👨‍👩‍👧‍👦 *В главных ролях:* {actors_text}\n\n📝 *Описание фильма \"{title_display}\":*\n\n{overview}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error sending movie poster: {e}")
            # Fallback to text-only message
            await context.bot.send_message(
                chat_id=chat_id,
                text=full_message,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=full_message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button presses from inline keyboards."""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    user_id = update.effective_user.id

    # Handle rating buttons
    if callback_data.startswith('rate_'):
        # Extract movie_id and rating
        parts = callback_data.split('_')
        tmdb_id = int(parts[1]) if parts[1] != 'none' else None
        rating = int(parts[2])

        if not tmdb_id:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"⚠️ Извините, не удалось сохранить оценку. ID фильма не найден."
            )
            return RECOMMENDATION

        # Get movie from database
        movie = db.get_movie_by_tmdb_id(tmdb_id)
        if not movie:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"⚠️ Извините, не удалось сохранить оценку. Фильм не найден в базе данных."
            )
            return RECOMMENDATION

        # Process rating
        success = await engine.process_user_feedback(user_id, tmdb_id, rating)

        if success:
            # Remove rating buttons from the original message
            await query.edit_message_reply_markup(reply_markup=None)

            # Escape movie title for Markdown
            escaped_title = escape_markdown(movie['title'])

            # Send confirmation message
            await query.message.reply_text(
                f"✅ Спасибо за оценку! Вы поставили фильму \"{escaped_title}\" оценку {rating}/10."
            )

            # Provide some feedback based on the rating
            if rating >= 8:
                feedback_message = (
                    "Отлично! Я учту, что вам очень понравился этот фильм "
                    f"и буду рекомендовать похожие в будущем."
                )
            elif rating >= 6:
                feedback_message = (
                    "Хорошо! Я учту ваше положительное мнение о фильме для будущих рекомендаций."
                )
            elif rating >= 4:
                feedback_message = (
                    "Понятно. Я учту ваше нейтральное отношение к этому фильму."
                )
            else:
                feedback_message = (
                    "Я учту, что вам не понравился этот фильм, и постараюсь избегать похожих рекомендаций."
                )

            await query.message.reply_text(feedback_message)
        else:
            await query.message.reply_text(
                "⚠️ Извините, произошла ошибка при сохранении вашей оценки. Пожалуйста, попробуйте позже."
            )

        return RECOMMENDATION

    # Handle similar movies button
    elif callback_data.startswith('similar_'):
        tmdb_id = int(callback_data.split('_')[1])

        # Get movie from database
        movie = db.get_movie_by_tmdb_id(tmdb_id)
        if not movie:
            await query.message.reply_text(
                "⚠️ Извините, не удалось найти похожие фильмы. Фильм не найден в базе данных."
            )
            return RECOMMENDATION

        # Escape movie title for Markdown
        escaped_title = escape_markdown(movie['title'])

        # Let user know we're working on it
        processing_message = await query.message.reply_text(
            f"🔍 Ищу фильмы, похожие на \"{escaped_title}\"..."
        )

        try:
            # Get similar movies
            similar_movies = await engine.get_similar_movies(movie['title'], user_id)

            # Delete processing message safely
            try:
                await processing_message.delete()
            except Exception as delete_error:
                logger.warning(f"Could not delete processing message: {delete_error}")

            if not similar_movies:
                await query.message.reply_text(
                    f"😕 Извините, не удалось найти фильмы, похожие на \"{escaped_title}\"."
                )
                return RECOMMENDATION

            # Send message with similar movies
            await query.message.reply_text(
                f"🎬 Вот фильмы, похожие на \"{escaped_title}\":",
                parse_mode='Markdown'
            )

            # Send movie cards for similar movies
            for similar_movie in similar_movies[:5]:  # Limit to 5
                await send_movie_card(update, context, similar_movie)

                # Store recommendation in history
                existing_movie = db.get_movie_by_tmdb_id(similar_movie.get('tmdb_id'))
                movie_id = existing_movie['id'] if existing_movie else db.add_movie(similar_movie)
                if movie_id:
                    db.add_user_history(user_id, movie_id, 'similar')

        except Exception as e:
            logger.error(f"Error finding similar movies: {e}")
            # Delete processing message safely
            try:
                await processing_message.delete()
            except Exception as delete_error:
                logger.warning(f"Could not delete processing message: {delete_error}")
            await query.message.reply_text(
                f"😟 Извините, произошла ошибка при поиске похожих фильмов: {str(e)}"
            )

        return RECOMMENDATION

    # Handle preference clearing
    elif callback_data == "clear_preferences":
        db.clear_user_preferences(user_id)
        await query.message.reply_text("✅ Ваши предпочтения успешно очищены.")
        return ConversationHandler.END

    # Handle history clearing
    elif callback_data == "clear_history":
        db.clear_user_history(user_id)
        await query.message.reply_text("✅ Ваша история рекомендаций успешно очищена.")
        return ConversationHandler.END

    # Handle confirmation for clearing all
    elif callback_data == "confirm_clear_all":
        db.clear_user_preferences(user_id)
        db.clear_user_history(user_id)
        await query.message.reply_text("✅ Все ваши предпочтения и история успешно очищены.")
        return ConversationHandler.END

    # Handle cancellation for clearing all
    elif callback_data == "cancel_clear":
        await query.message.reply_text("❌ Операция отменена. Ваши данные остались без изменений.")
        return ConversationHandler.END

    return RECOMMENDATION


def main() -> None:
    """Start the bot."""
    # Check if token is provided
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is missing! Please set it in your .env file.")
        sys.exit(1)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY is missing! Please set it in your .env file.")
        sys.exit(1)

    if not TMDB_API_KEY:
        logger.error("TMDB_API_KEY is missing! Please set it in your .env file.")
        sys.exit(1)

    # Create the Application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)],
        states={
            RECOMMENDATION: [
                CallbackQueryHandler(handle_button),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
            ],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("clear", clear_command))

    # Add conversation handler
    application.add_handler(conv_handler)

    # Add callback query handler for buttons outside conversation
    application.add_handler(CallbackQueryHandler(handle_button))

    # Start the Bot
    logger.info("Starting Movie Recommendation Bot...")
    application.run_polling()


if __name__ == '__main__':
    main()