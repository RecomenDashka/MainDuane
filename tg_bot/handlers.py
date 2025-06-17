# tg_bot/handlers.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from core.logger import get_logger
from tg_bot.keyboards import get_start_keyboard, get_post_action_keyboard, get_confirmation_keyboard
from tg_bot.formatter import format_movies_list, format_error, format_movie
from database.movies import MovieDatabase
from core.engine import RecommendationEngine
from agents.validator import QueryValidator
from agents.feedback import FeedbackAgent
from datetime import datetime

logger = get_logger("handlers")

# Определения состояний для ConversationHandler'ов (импортируются из main или дублируются)
RECOMMENDATION = 0
RATING_SELECT_MOVIE = 1
RATING_GET_SCORE = 2
FEEDBACK_COLLECTING = 3


# Вспомогательная функция для получения объекта сообщения для ответа
def get_message_object(update: Update):
    """
    Возвращает объект Message для ответа, независимо от того, пришло ли обновление от Message или CallbackQuery.
    """
    if update.message:
        return update.message
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message
    return None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start."""
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    db: MovieDatabase = context.bot_data.get('db')
    if db:
        db.add_user(user_id, username)
    else:
        logger.error("MovieDatabase не инициализирован в context.bot_data при /start.")

    target_message = get_message_object(update)
    if target_message:
        await target_message.reply_text(
            "Привет! Я помогу подобрать тебе фильм 🎬\n\nПросто напиши, что ты хочешь посмотреть. "
            "Например: 'фантастика про космос', 'комедия для всей семьи', 'что-то вроде Интерстеллара'.",
            reply_markup=get_post_action_keyboard()
        )
    return RECOMMENDATION


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help."""
    help_text = (
        "Я могу помочь вам найти фильмы, основываясь на ваших предпочтениях!\n\n"
        "Команды:\n"
        "/start - Начать взаимодействие с ботом\n"
        "/help - Показать это сообщение\n"
        "/recommend - Получить рекомендацию фильма (просто отправьте свой запрос)\n"
        "/rate - Оценить фильм\n"
        "/feedback - Оставить отзыв о работе бота\n"
        "/history - Посмотреть историю ваших рекомендаций и оценок\n\n"
        "Просто напишите, что вы хотите посмотреть, а я постараюсь подобрать подходящие фильмы 🎥"
    )
    target_message = get_message_object(update)
    if target_message:
        await target_message.reply_text(help_text, reply_markup=get_post_action_keyboard())


async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /recommend, позволяет начать рекомендацию."""
    target_message = get_message_object(update)
    if target_message:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.edit_text(
                "Отлично! Опишите, какой фильм вы хотите посмотреть. Например: 'фантастика про космос', 'комедия для всей семьи', 'что-то вроде Интерстеллара'.",
                reply_markup=get_post_action_keyboard()
            )
        else:
            await update.message.reply_text(
                "Отлично! Опишите, какой фильм вы хотите посмотреть. Например: 'фантастика про космос', 'комедия для всей семьи', 'что-то вроде Интерстеллара'.",
                reply_markup=get_post_action_keyboard()
            )
    return RECOMMENDATION


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Основной обработчик текстовых сообщений для получения рекомендаций.
    Валидирует запрос и вызывает RecommendationEngine.
    """
    user_id = update.effective_user.id
    user_query = update.message.text.strip()

    logger.info(f"Запрос от пользователя {user_id}: {user_query}")

    engine: RecommendationEngine = context.bot_data.get("recommendation_engine")
    query_validator: QueryValidator = context.bot_data.get("query_validator")
    db: MovieDatabase = context.bot_data.get("db")

    if not engine or not query_validator or not db:
        logger.error("Один из необходимых компонентов не найден в context.bot_data.")
        await update.message.reply_text(format_error("Ошибка инициализации бота. Пожалуйста, сообщите администратору."),
                                        reply_markup=get_post_action_keyboard())
        return RECOMMENDATION

    is_valid, reason = query_validator.validate_or_explain(user_query)
    if not is_valid:
        await update.message.reply_text(f"Извините, {reason}", reply_markup=get_post_action_keyboard())
        return RECOMMENDATION

    # Сохраняем последний запрос пользователя для возможных будущих "Ещё рекомендаций"
    context.user_data['last_user_query'] = user_query

    await update.message.chat.send_action(action="typing")
    await update.message.reply_text("🔍 Ищу рекомендации...")

    try:
        result = await engine.generate_recommendations(user_query, user_id)

        if 'error' in result:
            await update.message.reply_text(format_error(result['error']), reply_markup=get_post_action_keyboard())
        elif result.get("recommendations"):
            response_text = result.get('llm_response', 'Не удалось получить ответ.')
            recommended_movies = result.get('recommendations', [])

            await update.message.reply_text(response_text, parse_mode='Markdown')

            context.user_data['last_recommendations'] = []  # Очищаем список перед добавлением новых
            for movie in recommended_movies:
                movie_title = movie.get('title', 'Название неизвестно')
                release_date = movie.get('release_date', 'N/A')
                poster_url = movie.get('poster_url', '')

                year_only = release_date.split('-')[0] if release_date and len(release_date) >= 4 else 'N/A'
                caption = f"🎬 **{movie_title}** ({year_only})"

                movie_db_id = db.get_movie_id_by_tmdb_id(movie.get('tmdb_id'))
                if movie_db_id:
                    context.user_data['last_recommendations'].append({
                        'title': movie_title,
                        'tmdb_id': movie.get('tmdb_id'),
                        'db_id': movie_db_id
                    })

                # Формируем кнопки для действия с фильмом
                movie_action_buttons = [
                    InlineKeyboardButton("⭐ Оценить", callback_data=f"select_movie_for_rating_{movie_db_id}"),
                    InlineKeyboardButton("❤️ Сохранить", callback_data=f"save:{movie_db_id}"),
                ]

                # Кнопка "Показать детали" всегда присутствует
                details_button = InlineKeyboardButton("➡️ Показать детали", callback_data=f"details:{movie_db_id}")

                # Создаем клавиатуру без кнопок "Предыдущий/Следующий"
                keyboard_rows = [movie_action_buttons, [details_button]]
                reply_markup = InlineKeyboardMarkup(keyboard_rows)

                if poster_url:
                    try:
                        await update.message.reply_photo(
                            photo=poster_url,
                            caption=caption,
                            parse_mode='Markdown',
                            reply_markup=reply_markup
                        )
                    except Exception as photo_e:
                        logger.error(f"Failed to send photo for {movie_title}: {photo_e}")
                        await update.message.reply_text(f"{caption}\n(Не удалось загрузить постер)",
                                                        parse_mode='Markdown', reply_markup=reply_markup)
                else:
                    await update.message.reply_text(caption, parse_mode='Markdown', reply_markup=reply_markup)

            await update.message.reply_text("Что ещё вас интересует?", reply_markup=get_post_action_keyboard())

        else:
            await update.message.reply_text(
                "Извините, не удалось найти подходящие фильмы. Попробуйте переформулировать запрос.",
                reply_markup=get_post_action_keyboard()
            )

    except Exception as e:
        logger.error(f"Ошибка при получении рекомендаций для пользователя {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла непредвиденная ошибка при обработке запроса. Пожалуйста, попробуйте позже.",
            reply_markup=get_post_action_keyboard())

    return RECOMMENDATION


async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /rate, начало процесса оценки."""
    logger.debug(
        f"Entering rate_command. Update type: {type(update)}, Message: {update.message}, Callback: {update.callback_query}")

    user_id = update.effective_user.id
    db: MovieDatabase = context.bot_data.get('db')
    if not db:
        logger.error("MovieDatabase не инициализирован в context.bot_data при /rate.")
        target_message = get_message_object(update)
        if target_message:
            await target_message.reply_text(
                format_error("Ошибка инициализации бота. Пожалуйста, сообщите администратору."),
                reply_markup=get_post_action_keyboard())
        return RECOMMENDATION

    user_history = db.get_user_history(user_id)
    user_ratings = db.get_user_ratings(user_id)
    rated_movie_ids = {r['movie_id'] for r in user_ratings}

    potential_movies_to_rate = []
    seen_db_ids = set()

    for record in user_history:
        movie_db_id = record.get('movie_id')
        if movie_db_id and movie_db_id not in rated_movie_ids and movie_db_id not in seen_db_ids:
            movie_details = db.get_movie(movie_db_id)
            if movie_details:
                potential_movies_to_rate.append({
                    'db_id': movie_db_id,
                    'title': movie_details.get('title')
                })
                seen_db_ids.add(movie_db_id)

    if not potential_movies_to_rate:
        target_message = get_message_object(update)
        if target_message:
            await target_message.reply_text("У вас нет недавних фильмов, которые можно оценить. "
                                            "Пожалуйста, запросите новые фильмы или просмотрите историю.",
                                            reply_markup=get_post_action_keyboard())
        return ConversationHandler.END  # Завершаем ConversationHandler, если нет фильмов

    keyboard_buttons = []
    for movie in potential_movies_to_rate:
        keyboard_buttons.append(
            [InlineKeyboardButton(movie['title'], callback_data=f"select_movie_for_rating_{movie['db_id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    target_message = get_message_object(update)
    if target_message:
        if update.callback_query:
            await update.callback_query.answer()
            try:
                # Если это callback от inline-кнопки (например, из post_action_keyboard)
                await update.callback_query.message.edit_text("Какой фильм вы хотите оценить?",
                                                              reply_markup=reply_markup)
            except Exception as e:
                logger.warning(f"Failed to edit message in rate_command from callback: {e}. Sending new message.")
                await target_message.reply_text("Какой фильм вы хотите оценить?", reply_markup=reply_markup)
        else:
            # Если это текстовая команда /rate
            await update.message.reply_text("Какой фильм вы хотите оценить?", reply_markup=reply_markup)
    return RATING_SELECT_MOVIE


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /feedback, начало процесса сбора обратной связи."""
    logger.debug(
        f"Entering feedback_command. Update type: {type(update)}, Message: {update.message}, Callback: {update.callback_query}")

    target_message = get_message_object(update)
    if target_message:
        if update.callback_query:
            await update.callback_query.answer()
            try:
                # Если это callback от inline-кнопки (например, из post_action_keyboard)
                await update.callback_query.message.edit_text(
                    "Спасибо за желание помочь! Пожалуйста, напишите ваш отзыв о работе бота."
                    "Я сохраню его анонимно.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel")]])
                )
            except Exception as e:
                logger.warning(f"Failed to edit message in feedback_command from callback: {e}. Sending new message.")
                await target_message.reply_text(
                    "Спасибо за желание помочь! Пожалуйста, напишите ваш отзыв о работе бота."
                    "Я сохраню его анонимно.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel")]])
                )
        else:
            # Если это текстовая команда /feedback
            await update.message.reply_text(
                "Спасибо за желание помочь! Пожалуйста, напишите ваш отзыв о работе бота."
                "Я сохраню его анонимно.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel")]])
            )

    # Сохраняем текст последнего запроса пользователя для привязки к отзыву
    context.user_data['last_user_query_for_feedback'] = update.message.text if update.message else "N/A (from callback)"
    return FEEDBACK_COLLECTING


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /history."""
    user_id = update.effective_user.id
    db: MovieDatabase = context.bot_data.get('db')
    if not db:
        logger.error("MovieDatabase не инициализирован в context.bot_data при /history.")
        # Используем update.effective_chat.send_message, так как update.message может быть None
        await context.bot.send_message(chat_id=user_id, text=format_error(
            "Ошибка инициализации бота. Пожалуйста, сообщите администратору."), reply_markup=get_post_action_keyboard())
        return

    history_records = db.get_user_history(user_id)

    if not history_records:
        await context.bot.send_message(chat_id=user_id, text="Ваша история рекомендаций и взаимодействий пуста.",
                                       reply_markup=get_post_action_keyboard())
        return

    history_text = "Ваша история:\n"
    for record in history_records:
        movie_details = db.get_movie(record['movie_id'])
        movie_title = movie_details.get('title', 'Неизвестный фильм') if movie_details else 'Неизвестный фильм'
        action = record['action_type']
        try:
            timestamp_dt = datetime.fromisoformat(str(record['timestamp']))
            timestamp_formatted = timestamp_dt.strftime('%d.%m.%Y %H:%M')
        except ValueError:
            timestamp_formatted = str(record['timestamp'])
            logger.warning(f"Некорректный формат timestamp в истории: {record['timestamp']}")

        history_text += f"- **«{movie_title}»** ({action}) от {timestamp_formatted}\n"

    await context.bot.send_message(chat_id=user_id, text=history_text, parse_mode='Markdown',
                                   reply_markup=get_post_action_keyboard())


async def view_saved_movies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик для просмотра сохраненных фильмов."""
    user_id = update.effective_user.id
    db: MovieDatabase = context.bot_data.get('db')
    if not db:
        logger.error("MovieDatabase не инициализирован в context.bot_data при view_saved_movies_command.")
        await context.bot.send_message(chat_id=user_id, text=format_error(
            "Ошибка инициализации бота. Пожалуйста, сообщите администратору."), reply_markup=get_post_action_keyboard())
        return

    saved_movies_records = db.get_user_history(user_id, action_type='saved')

    if not saved_movies_records:
        await context.bot.send_message(chat_id=user_id, text="У вас пока нет сохраненных фильмов.",
                                       reply_markup=get_post_action_keyboard())
        return

    saved_movies_details = []
    for record in saved_movies_records:
        movie = db.get_movie(record['movie_id'])
        if movie:
            saved_movies_details.append(movie)

    if not saved_movies_details:
        await context.bot.send_message(chat_id=user_id, text="Не удалось получить детали для сохраненных фильмов.",
                                       reply_markup=get_post_action_keyboard())
        return

    saved_movies_titles = [
        f"**{format_movie_title_for_display(m.get('title'))}** ({m.get('release_date', '')[:4] or 'N/A'})" for m in
        saved_movies_details]
    llm_prompt = (
        f"У вас есть сохраненные фильмы: {', '.join(saved_movies_titles)}. "
        f"Напиши короткое, дружелюбное сообщение, представляющее этот список сохраненных фильмов. "
        f"Упоминай только эти фильмы, без лишних вступлений, сразу к делу."
    )
    llm_generator = context.bot_data.get('llm_generator')
    llm_response = await llm_generator.generate(prompt=llm_prompt,
                                                system_prompt="Ты дружелюбный ассистент по фильмам. Предоставь информацию о фильмах.")

    await context.bot.send_message(chat_id=user_id, text=llm_response, parse_mode='Markdown')

    for movie in saved_movies_details:
        movie_title = movie.get('title', 'Название неизвестно')
        release_date = movie.get('release_date', 'N/A')
        poster_url = movie.get('poster_url', '')

        year_only = release_date.split('-')[0] if release_date and len(release_date) >= 4 else 'N/A'
        caption = f"🎬 **{movie_title}** ({year_only})"

        movie_db_id = movie.get('id')

        if poster_url:
            try:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=poster_url,
                    caption=caption,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⭐ Оценить", callback_data=f"select_movie_for_rating_{movie_db_id}")],
                        [InlineKeyboardButton("➡️ Показать детали", callback_data=f"details:{movie_db_id}")]
                    ])
                )
            except Exception as photo_e:
                logger.error(f"Failed to send photo for {movie_title}: {photo_e}")
                await context.bot.send_message(chat_id=user_id, text=f"{caption}\n(Не удалось загрузить постер)",
                                               parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=user_id, text=caption, parse_mode='Markdown',
                                           reply_markup=InlineKeyboardMarkup([
                                               [InlineKeyboardButton("⭐ Оценить",
                                                                     callback_data=f"select_movie_for_rating_{movie_db_id}")],
                                               [InlineKeyboardButton("➡️ Показать детали",
                                                                     callback_data=f"details:{movie_db_id}")]
                                           ]))
    await context.bot.send_message(chat_id=user_id, text="Что ещё вас интересует?",
                                   reply_markup=get_post_action_keyboard())


def format_movie_title_for_display(title: str) -> str:
    """
    Форматирует название фильма, удаляя символы, которые могут сломать Markdown.
    """
    return title.replace('*', '').replace('_', '').replace('`', '')

