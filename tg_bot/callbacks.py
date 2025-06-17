# tg_bot/callbacks.py
from typing import List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest
from database.movies import MovieDatabase
from tg_bot.formatter import format_movie, format_movies_list, format_error
from tg_bot.keyboards import get_rating_keyboard, get_post_action_keyboard, get_confirmation_keyboard
from core.logger import get_logger
from core.engine import RecommendationEngine
from agents.feedback import FeedbackAgent

logger = get_logger("callbacks")

# Определения состояний (дублируются здесь для ясности, но обычно импортируются)
RECOMMENDATION = 0
RATING_SELECT_MOVIE = 1
RATING_GET_SCORE = 2
FEEDBACK_COLLECTING = 3


async def save_movie_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик колбэка для сохранения фильма в избранное/историю.
    Callback data: "save:{movie_db_id}"
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()  # Отвечаем на callbackQuery, чтобы убрать "часики"

    try:
        _, movie_db_id_str = query.data.split(":", 1)
        movie_db_id = int(movie_db_id_str)
    except (ValueError, IndexError):
        logger.error(f"Некорректный callback_data для save_movie_callback: {query.data}")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: Некорректные данные фильма."),
                                       reply_markup=get_post_action_keyboard())
        return

    db: MovieDatabase = context.bot_data.get('db')
    if not db:
        logger.error("MovieDatabase не инициализирован в context.bot_data.")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: База данных недоступна."),
                                       reply_markup=get_post_action_keyboard())
        return

    movie_details = db.get_movie(movie_db_id)
    movie_title = movie_details.get('title', 'Неизвестный фильм') if movie_details else 'Неизвестный фильм'

    if db.add_user_history(user_id, movie_db_id, "saved"):
        await context.bot.send_message(chat_id=user_id, text=f"✅ Фильм **«{movie_title}»** добавлен в сохранённые!",
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())
        logger.info(f"Фильм ID {movie_db_id} сохранен пользователем {user_id}.")
    else:
        await context.bot.send_message(chat_id=user_id, text=format_error(
            f"Произошла ошибка при сохранении фильма **«{movie_title}»**."), parse_mode='Markdown',
                                       reply_markup=get_post_action_keyboard())
        logger.error(f"Не удалось сохранить фильм ID {movie_db_id} для пользователя {user_id}.")


async def rate_movie_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик колбэка для оценки фильма.
    Callback data: "rate:{movie_db_id}:{rating_score}"
    Это прямой обработчик оценки, не часть ConversationHandler.
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        _, movie_db_id_str, rating_score_str = query.data.split(":", 2)
        movie_db_id = int(movie_db_id_str)
        rating = int(rating_score_str)
    except (ValueError, IndexError):
        logger.error(f"Некорректный callback_data для rate_movie_callback: {query.data}")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: Некорректные данные оценки фильма."),
                                       reply_markup=get_post_action_keyboard())
        return

    db: MovieDatabase = context.bot_data.get('db')
    if not db:
        logger.error("MovieDatabase не инициализирован в context.bot_data.")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: База данных недоступна."),
                                       reply_markup=get_post_action_keyboard())
        return

    movie_details = db.get_movie(movie_db_id)
    movie_title = movie_details.get('title', 'Неизвестный фильм') if movie_details else 'Неизвестный фильм'

    if db.add_rating(user_id, movie_db_id, rating):
        await context.bot.send_message(chat_id=user_id,
                                       text=f"Спасибо! Вы оценили фильм **«{movie_title}»** на {rating}/10. ⭐",
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())
        logger.info(f"Пользователь {user_id} оценил фильм ID {movie_db_id} на {rating}.")
    else:
        await context.bot.send_message(chat_id=user_id, text=format_error(
            f"Произошла ошибка при сохранении вашей оценки для **«{movie_title}»**."),
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())
        logger.error(f"Не удалось сохранить оценку {rating} для фильма ID {movie_db_id} от пользователя {user_id}.")


async def select_movie_for_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Callback-обработчик для выбора фильма для оценки в рамках ConversationHandler.
    (Ведет к RATING_GET_SCORE)
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.debug(f"Entering select_movie_for_rating. Callback data: {query.data}")

    try:
        db_id = int(query.data.replace("select_movie_for_rating_", ""))
    except ValueError as e:
        logger.error(f"Некорректный callback_data для select_movie_for_rating: {query.data}, Error: {e}")
        await context.bot.send_message(chat_id=user_id,
                                       text=format_error("Ошибка: Некорректные данные фильма для оценки."),
                                       reply_markup=get_post_action_keyboard())
        return ConversationHandler.END

    context.user_data['movie_to_rate_db_id'] = db_id

    db_instance: MovieDatabase = context.bot_data.get('db')
    if not db_instance:
        logger.error("MovieDatabase не инициализирован в context.bot_data (select_movie_for_rating).")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: База данных недоступна."),
                                       reply_markup=get_post_action_keyboard())
        return ConversationHandler.END

    movie_details = db_instance.get_movie(db_id)
    movie_title = movie_details.get('title', 'этот фильм') if movie_details else 'этот фильм'

    reply_markup = get_rating_keyboard(db_id)

    try:
        await query.edit_message_text(f"Какую оценку (от 0 до 10) вы дадите фильму **«{movie_title}»**?",
                                      reply_markup=reply_markup, parse_mode='Markdown')
        logger.debug(f"Edited message for rating selection for user {user_id}")
    except BadRequest as e:
        logger.warning(
            f"Ошибка при редактировании сообщения для выбора оценки для {user_id}: {e}. Отправка нового сообщения.")
        await context.bot.send_message(chat_id=user_id,
                                       text=f"Какую оценку (от 0 до 10) вы дадите фильму **«{movie_title}»**?",
                                       reply_markup=reply_markup, parse_mode='Markdown')

    return RATING_GET_SCORE


async def get_rating_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Callback-обработчик после выбора оценки в рамках ConversationHandler.
    (Завершает ConversationHandler)
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    logger.debug(f"Entering get_rating_score. Update type: {type(update)}, Callback: {query.data}")

    try:
        _, movie_db_id_str, rating_score_str = query.data.split(":", 2)
        movie_db_id = int(movie_db_id_str)
        rating = int(rating_score_str)
        logger.debug(f"Parsed rating data: movie_id={movie_db_id}, rating={rating}")
    except (ValueError, IndexError) as e:
        logger.error(f"Некорректный callback_data для get_rating_score: {query.data}, Error: {e}")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: Некорректные данные оценки фильма."),
                                       reply_markup=get_post_action_keyboard())
        return ConversationHandler.END

    db: MovieDatabase = context.bot_data.get('db')
    if not db:
        logger.error("MovieDatabase не инициализирован в context.bot_data.")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: База данных недоступна."),
                                       reply_markup=get_post_action_keyboard())
        return ConversationHandler.END

    movie_details = db.get_movie(movie_db_id)
    movie_title = movie_details.get('title', 'Неизвестный фильм') if movie_details else 'Неизвестный фильм'

    if db.add_rating(user_id, movie_db_id, rating):
        await context.bot.send_message(chat_id=user_id,
                                       text=f"Спасибо! Вы оценили фильм **«{movie_title}»** на {rating}/10. ⭐",
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())
        logger.info(f"Пользователь {user_id} оценил фильм ID {movie_db_id} на {rating}.")
    else:
        await context.bot.send_message(chat_id=user_id, text=format_error(
            f"Произошла ошибка при сохранении вашей оценки для **«{movie_title}»**."),
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())
        logger.error(f"Не удалось сохранить оценку {rating} для фильма ID {movie_db_id} от пользователя {user_id}.")

    # Очищаем временные данные, связанные с оценкой
    if 'movie_to_rate_db_id' in context.user_data:
        del context.user_data['movie_to_rate_db_id']
    if 'last_recommendations' in context.user_data:
        context.user_data['last_recommendations'] = [rec for rec in context.user_data['last_recommendations'] if
                                                     rec.get('db_id') != movie_db_id]

    return ConversationHandler.END


async def collect_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик для сбора текста обратной связи."""
    logger.debug(
        f"Entering collect_feedback. Update type: {type(update)}, Message text: {update.message.text if update.message else 'N/A'}")

    user_id = update.effective_user.id
    feedback_text = update.message.text
    last_query = context.user_data.get('last_user_query_for_feedback', 'N/A (from callback)')

    feedback_agent: FeedbackAgent = context.bot_data.get('feedback_agent')
    if not feedback_agent:
        logger.error("FeedbackAgent не инициализирован в context.bot_data.")
        await update.message.reply_text(format_error("Ошибка: Агент обратной связи недоступен."),
                                        reply_markup=get_post_action_keyboard())
        return ConversationHandler.END

    if feedback_agent.save_feedback(user_id=str(user_id), query=last_query, feedback=feedback_text):
        await update.message.reply_text("Спасибо! Ваш отзыв успешно сохранен.", reply_markup=get_post_action_keyboard())
        logger.info(f"Отзыв от пользователя {user_id} сохранен: '{feedback_text[:50]}...'")
    else:
        await update.message.reply_text(
            format_error("Произошла ошибка при сохранении отзыва. Пожалуйста, попробуйте еще раз."),
            reply_markup=get_post_action_keyboard())
        logger.error(f"Не удалось сохранить отзыв от пользователя {user_id}: '{feedback_text[:50]}...'")

    if 'last_user_query_for_feedback' in context.user_data:
        del context.user_data['last_user_query_for_feedback']

    return ConversationHandler.END


async def show_movie_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Callback-обработчик для показа полной информации о фильме.
    Callback data: "details:{movie_db_id}"
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    db: MovieDatabase = context.bot_data.get('db')
    if not db:
        logger.error("MovieDatabase не инициализирован в context.bot_data.")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: База данных недоступна."),
                                       reply_markup=get_post_action_keyboard())
        return

    try:
        _, movie_db_id_str = query.data.split(":", 1)
        movie_db_id = int(movie_db_id_str)
    except (ValueError, IndexError):
        logger.error(f"Некорректный callback_data для show_movie_details_callback: {query.data}")
        await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: Некорректные данные фильма."),
                                       reply_markup=get_post_action_keyboard())
        return

    movie = db.get_movie(movie_db_id)
    if movie:
        formatted_text = format_movie(movie)
        # Клавиатура деталей, без кнопок навигации "Предыдущий/Следующий"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("⭐ Оценить", callback_data=f"select_movie_for_rating_{movie['id']}"),
             InlineKeyboardButton("❤️ Сохранить", callback_data=f"save:{movie['id']}")],
            [InlineKeyboardButton("🔙 Назад к рекомендациям", callback_data="back:recommendations_list")]
        ])

        try:
            if query.message.photo:
                await query.message.edit_caption(
                    caption=formatted_text,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
            else:
                await query.message.edit_text(
                    formatted_text,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
            logger.info(f"Пользователю {user_id} показаны детали фильма ID: {movie_db_id}.")
        except BadRequest as e:
            logger.warning(
                f"Ошибка при редактировании сообщения (details) для {user_id}: {e}. Отправка нового сообщения.")
            await context.bot.send_message(chat_id=user_id, text=formatted_text, parse_mode='Markdown',
                                           reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=user_id, text=format_error("Фильм не найден в базе данных."),
                                       reply_markup=get_post_action_keyboard())
        logger.warning(f"Фильм ID {movie_db_id} не найден в БД для show_movie_details_callback.")


async def more_recommendations_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Callback-обработчик для запроса дополнительных рекомендаций.
    Callback data: "get_recommendations"
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("Загружаю ещё рекомендации...", show_alert=False)

    engine: RecommendationEngine = context.bot_data.get('recommendation_engine')
    if not engine:
        logger.error("RecommendationEngine не инициализирован в context.bot_data.")
        await context.bot.send_message(chat_id=user_id,
                                       text=format_error("Ошибка: Рекомендательный движок недоступен."),
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())
        return

    last_query = context.user_data.get('last_user_query', "посоветуй что-нибудь интересное")

    try:
        await query.edit_message_text("🔍 Ищу ещё рекомендации...", reply_markup=None, parse_mode='Markdown')

        result = await engine.generate_recommendations(last_query, user_id)

        if 'error' in result:
            await context.bot.send_message(chat_id=user_id, text=format_error(result['error']), parse_mode='Markdown',
                                           reply_markup=get_post_action_keyboard())
        elif result.get("recommendations"):
            response_text = result.get('llm_response', 'Не удалось получить ответ.')
            recommended_movies = result.get('recommendations', [])

            await context.bot.send_message(chat_id=user_id, text=response_text, parse_mode='Markdown',
                                           reply_markup=None)

            context.user_data['last_recommendations'] = []
            db: MovieDatabase = context.bot_data.get('db')

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

                # Формируем кнопки для действия с фильмом, без навигации
                movie_action_buttons = [
                    InlineKeyboardButton("⭐ Оценить", callback_data=f"select_movie_for_rating_{movie_db_id}"),
                    InlineKeyboardButton("❤️ Сохранить", callback_data=f"save:{movie_db_id}"),
                ]

                details_button = InlineKeyboardButton("➡️ Показать детали", callback_data=f"details:{movie_db_id}")

                keyboard_rows = [movie_action_buttons, [details_button]]
                reply_markup = InlineKeyboardMarkup(keyboard_rows)

                if poster_url:
                    try:
                        await context.bot.send_photo(
                            chat_id=user_id,
                            photo=poster_url,
                            caption=caption,
                            parse_mode='Markdown',
                            reply_markup=reply_markup
                        )
                    except Exception as photo_e:
                        logger.error(f"Failed to send photo for {movie_title}: {photo_e}")
                        await context.bot.send_message(chat_id=user_id,
                                                       text=f"{caption}\n(Не удалось загрузить постер)",
                                                       parse_mode='Markdown', reply_markup=reply_markup)
                else:
                    await context.bot.send_message(chat_id=user_id, text=caption, parse_mode='Markdown',
                                                   reply_markup=reply_markup)

            await context.bot.send_message(chat_id=user_id, text="Что ещё вас интересует?",
                                           reply_markup=get_post_action_keyboard())

        else:
            await context.bot.send_message(chat_id=user_id,
                                           text="Извините, не удалось найти подходящие фильмы. Попробуйте переформулировать запрос.",
                                           reply_markup=get_post_action_keyboard()
                                           )
    except Exception as e:
        logger.error(f"Ошибка при запросе ещё рекомендаций для пользователя {user_id}: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=format_error(
            "Произошла непредвиденная ошибка при обработке запроса. Пожалуйста, попробуйте позже."),
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Общий обработчик для кнопки "Отмена" или "Нет" в клавиатурах подтверждения.
    Callback data: "cancel"
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("Отменено.")
    try:
        await query.message.edit_text("Действие отменено.", reply_markup=get_post_action_keyboard())
    except BadRequest:
        await context.bot.send_message(chat_id=user_id, text="Действие отменено.",
                                       reply_markup=get_post_action_keyboard())

    return ConversationHandler.END


async def confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик для кнопок подтверждения.
    Callback data: "confirm:{action}:{payload}"
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        parts = query.data.split(":", 2)
        if len(parts) < 3:
            raise ValueError("Недостаточно частей в callback_data для подтверждения.")

        action_type = parts[1]
        payload_data = parts[2]

        db: MovieDatabase = context.bot_data.get('db')
        if not db:
            logger.error("MovieDatabase не инициализирован в context.bot_data.")
            await context.bot.send_message(chat_id=user_id, text=format_error("Ошибка: База данных недоступна."),
                                           reply_markup=get_post_action_keyboard())
            return

        response_message = "Действие выполнено."

        if action_type == "clear_history":
            if db.clear_user_history(user_id):
                response_message = "Ваша история успешно очищена."
            else:
                response_message = format_error("Ошибка при очистке истории.")
        else:
            response_message = format_error("Неизвестное действие подтверждения.")
            logger.warning(f"Получено неизвестное действие подтверждения: {action_type}")

        try:
            await query.message.edit_text(response_message, parse_mode='Markdown',
                                          reply_markup=get_post_action_keyboard())
        except BadRequest:
            await context.bot.send_message(chat_id=user_id, text=response_message, parse_mode='Markdown',
                                           reply_markup=get_post_action_keyboard())

        logger.info(f"Действие подтверждения '{action_type}' выполнено для пользователя {user_id}.")

    except (ValueError, IndexError, KeyError) as e:
        logger.error(f"Некорректный callback_data или ошибка при обработке подтверждения: {query.data}, {e}")
        await context.bot.send_message(chat_id=user_id,
                                       text=format_error("Ошибка: Не удалось выполнить действие подтверждения."),
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в confirmation_callback: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=format_error("Произошла непредвиденная ошибка."),
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())


async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик для кнопки 'Назад'.
    Callback data: "back:{target}"
    """
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        _, target = query.data.split(":", 1)
        if target == "main_menu":
            try:
                await query.message.edit_text(
                    "Вы вернулись в главное меню. Чем могу помочь?",
                    reply_markup=get_post_action_keyboard()
                )
            except BadRequest:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="Вы вернулись в главное меню. Чем могу помочь?",
                    reply_markup=get_post_action_keyboard()
                )
        elif target == "recommendations_list":
            last_recs_info: List[Dict[str, Any]] = context.user_data.get('last_recommendations', [])
            if last_recs_info:
                formatted_list = format_movies_list(last_recs_info)
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Вот последние рекомендации:\n{formatted_list}",
                    parse_mode='Markdown',
                    reply_markup=get_post_action_keyboard()
                )
                try:
                    await query.delete_message()
                except BadRequest as e:
                    logger.warning(f"Не удалось удалить старое сообщение при возврате к рекомендациям: {e}")
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="Вернулись назад. У вас нет недавних рекомендаций. "
                         "Пожалуйста, запросите новые фильмы.",
                    reply_markup=get_post_action_keyboard()
                )
                try:
                    await query.delete_message()
                except BadRequest as e:
                    logger.warning(f"Не удалось удалить старое сообщение при возврате без рекомендаций: {e}")
        else:
            await context.bot.send_message(chat_id=user_id, text="Действие 'Назад' выполнено.",
                                           reply_markup=get_post_action_keyboard())
            try:
                await query.delete_message()
            except BadRequest as e:
                logger.warning(f"Не удалось удалить старое сообщение при общем возврате: {e}")

        logger.info(f"Пользователь {user_id} вернулся к цели: {target}.")
    except (ValueError, IndexError) as e:
        logger.error(f"Некорректный callback_data для back_callback: {query.data}, {e}")
        await context.bot.send_message(chat_id=user_id,
                                       text=format_error("Ошибка: Не удалось выполнить действие 'Назад'."),
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в back_callback: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id,
                                       text=format_error("Произошла непредвиденная ошибка при возврате."),
                                       parse_mode='Markdown', reply_markup=get_post_action_keyboard())

