import re
import asyncio
import difflib
from typing import List, Dict, Any, Optional, Tuple
from core.logger import get_logger

from agents.llm_generator import LLMGenerator
from agents.tmdb_agent import TMDBAgent
from agents.translator import TranslatorAgent
from database.movies import MovieDatabase

logger = get_logger("recommendation_engine")


class RecommendationEngine:
    """
    Класс для генерации рекомендаций фильмов, использующий LLM для понимания запроса,
    TMDB для получения информации о фильмах, и TranslatorAgent для обработки языков.
    Он оркестрирует взаимодействие между этими компонентами.
    """

    def __init__(
            self,
            llm_generator: LLMGenerator,
            tmdb_agent: TMDBAgent,
            db: MovieDatabase,
            translator_agent: TranslatorAgent,
            initial_system_prompt: str = (
                    "Ты — умный и креативный помощник по рекомендации фильмов. "
                    "На основе запроса пользователя, предложи 3-5 РЕАЛЬНЫХ, ПОПУЛЯРНЫХ фильмов, "
                    "которые могли бы ему понравиться. "
                    "Список фильмов должен быть в виде простого перечисления, БЕЗ пояснений, "
                    "каждый фильм в двойных угловых скобках «Название фильма» и в конце года выпуска (Год)."
                    "Если сомневаешься, не выдумывай названия и не предлагай несуществующие фильмы. "
                    "Отвечай только на русском языке. "
                    "Пример ответа: «Матрица» (1999), «Начало» (2010), «Дюна» (2021)."
            ),
            final_system_prompt: str = (
                    "Ты — дружелюбный ассистент по фильмам. "
                    "Тебе будут предоставлены названия фильмов. "
                    "Напиши короткую, привлекательную рекомендацию, используя эти фильмы. "
                    "Упомяни каждый фильм, включая его название и год. "
                    "Форматируй названия как **Название фильма** (Год). "
                    "Отвечай только на русском языке, без лишних вступлений, сразу к делу."
            ),
    ):
        self.llm_generator = llm_generator
        self.tmdb_agent = tmdb_agent
        self.db = db
        self.translator_agent = translator_agent
        self.initial_system_prompt = initial_system_prompt
        self.final_system_prompt = final_system_prompt

    def _escape_markdown_v2(self, text: str) -> str:
        """
        Экранирует специальные символы MarkdownV2 для текста Telegram.
        https://core.telegram.org/bots/api#markdownv2-style
        """
        if not isinstance(text, str):
            return ""
        escape_chars = r'_*[]()~`>#+-.=|{}!'

        escaped_text = ""
        for char in text:
            if char in escape_chars:
                escaped_text += '\\' + char
            else:
                escaped_text += char
        return escaped_text

    async def _extract_movie_titles_from_llm_response(self, llm_response_text: str) -> List[Tuple[str, Optional[int]]]:
        """
        Извлекает названия фильмов и год выпуска из ответа LLM.
        Приоритет: «Название фильма» (Год), затем "Название фильма" (Год),
        затем Название фильма (Год).

        Args:
            llm_response_text: Текст ответа LLM.

        Returns:
            Список кортежей (название_фильма, год_выпуска_или_None).
        """
        extracted_titles: List[Tuple[str, Optional[int]]] = []

        patterns = [
            r'«([^»]+)»\s*\((\d{4})\)',  # «Название» (Год)
            r'"([^"]+)"\s*\((\d{4})\)',  # "Название" (Год)
            r'([^,;]+?)\s*\((\d{4})\)'  # Название (Год) - добавлен этот паттерн
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, llm_response_text):
                title = match.group(1).strip()  # Обрезаем пробелы
                year_str = match.group(2)
                year = int(year_str) if year_str else None

                if (title, year) not in extracted_titles:
                    extracted_titles.append((title, year))

        logger.info(f"Extracted initial candidate titles: {extracted_titles}")
        return extracted_titles

    def _clean_title_for_comparison(self, title: str) -> str:
        """
        Очищает название фильма для сравнения: удаляет спецсимволы и приводит к нижнему регистру.
        """
        if not isinstance(title, str):
            return ""
        cleaned = re.sub(r"[^\w\s]", "", title)
        return " ".join(cleaned.split()).lower()

    async def _validate_movie_relevance(self, user_query: str, llm_suggested_title_ru: str,
                                        movie_details: Dict[str, Any]) -> bool:
        """
        Валидирует релевантность найденного фильма, используя нечеткое сопоставление названий.
        Удалена проверка года.

        Args:
            user_query: Исходный запрос пользователя.
            llm_suggested_title_ru: Название фильма, предложенное LLM (на русском).
            movie_details: Полные детали фильма из TMDB.

        Returns:
            True, если фильм считается релевантным (название достаточно похоже), иначе False.
        """
        TMDB_FUZZY_THRESHOLD = 0.4

        tmdb_title_localized = movie_details.get('title', '')
        tmdb_title_original = movie_details.get('original_title', '')

        cleaned_user_query = self._clean_title_for_comparison(user_query)
        cleaned_llm_suggested_title = self._clean_title_for_comparison(llm_suggested_title_ru)
        cleaned_tmdb_localized_title = self._clean_title_for_comparison(tmdb_title_localized)
        cleaned_tmdb_original_title = self._clean_title_for_comparison(tmdb_title_original)

        tmdb_original_title_ru_translated = ""
        if cleaned_tmdb_original_title and self.translator_agent:
            original_lang = await self.translator_agent.detect_language(tmdb_title_original)
            if original_lang != 'ru':
                tmdb_original_title_ru_translated = await self.translator_agent.translate_to_russian(
                    tmdb_title_original)
                tmdb_original_title_ru_translated = self._clean_title_for_comparison(tmdb_original_title_ru_translated)

        comparisons = []

        if cleaned_llm_suggested_title:
            if cleaned_tmdb_localized_title:
                ratio = difflib.SequenceMatcher(None, cleaned_llm_suggested_title, cleaned_tmdb_localized_title).ratio()
                comparisons.append(
                    f"LLM_vs_TMDB_Localized ('{cleaned_llm_suggested_title}' vs '{cleaned_tmdb_localized_title}'): {ratio:.2f}")
                if ratio >= TMDB_FUZZY_THRESHOLD:
                    logger.info(
                        f"Fuzzy match found (LLM vs Localized TMDB) for '{tmdb_title_localized}'. Ratio: {ratio:.2f}")
                    return True
            if tmdb_original_title_ru_translated:
                ratio = difflib.SequenceMatcher(None, cleaned_llm_suggested_title,
                                                tmdb_original_title_ru_translated).ratio()
                comparisons.append(
                    f"LLM_vs_TMDB_Original_Translated ('{cleaned_llm_suggested_title}' vs '{tmdb_original_title_ru_translated}'): {ratio:.2f}")
                if ratio >= TMDB_FUZZY_THRESHOLD:
                    logger.info(
                        f"Fuzzy match found (LLM vs Translated Original TMDB) for '{tmdb_title_localized}'. Ratio: {ratio:.2f}")
                    return True

        if len(cleaned_user_query.split()) > 1 and len(cleaned_user_query) > 5:
            if cleaned_tmdb_localized_title:
                ratio = difflib.SequenceMatcher(None, cleaned_user_query, cleaned_tmdb_localized_title).ratio()
                comparisons.append(
                    f"User_vs_TMDB_Localized ('{cleaned_user_query}' vs '{cleaned_tmdb_localized_title}'): {ratio:.2f}")
                if ratio >= TMDB_FUZZY_THRESHOLD:
                    logger.info(
                        f"Fuzzy match found (User vs Localized TMDB) for '{tmdb_title_localized}'. Ratio: {ratio:.2f}")
                    return True
            if cleaned_tmdb_original_title:
                ratio = difflib.SequenceMatcher(None, cleaned_user_query, cleaned_tmdb_original_title).ratio()
                comparisons.append(
                    f"User_vs_TMDB_Original ('{cleaned_user_query}' vs '{cleaned_tmdb_original_title}'): {ratio:.2f}")
                if ratio >= TMDB_FUZZY_THRESHOLD:
                    logger.info(
                        f"Fuzzy match found (User vs Original TMDB) for '{tmdb_title_localized}'. Ratio: {ratio:.2f}")
                    return True
            if tmdb_original_title_ru_translated:
                ratio = difflib.SequenceMatcher(None, cleaned_user_query, tmdb_original_title_ru_translated).ratio()
                comparisons.append(
                    f"User_vs_TMDB_Original_Translated ('{cleaned_user_query}' vs '{tmdb_original_title_ru_translated}'): {ratio:.2f}")
                if ratio >= TMDB_FUZZY_THRESHOLD:
                    logger.info(
                        f"Fuzzy match found (User vs Translated Original TMDB) for '{tmdb_title_localized}'. Ratio: {ratio:.2f}")
                    return True

        logger.info(f"No sufficient fuzzy match for '{tmdb_title_localized}'. Comparisons: {'; '.join(comparisons)}")
        return False

    async def generate_recommendations(self, user_query: str, user_id: int) -> Dict[str, Any]:
        """
        Генерирует рекомендации фильмов на основе запроса пользователя,
        интегрируя LLM для генерации, TMDB для верификации и обогащения,
        и TranslatorAgent для языковой адаптации.

        Args:
            user_query: Строка запроса пользователя.
            user_id: Идентификатор пользователя для сохранения истории и предпочтений.

        Returns:
            Словарь, содержащий финальный ответ LLM ('llm_response') и список
            словарей с подробной информацией о рекомендованных фильмах ('recommendations').
            В случае ошибки возвращает словарь с ключом 'error'.
        """
        try:
            logger.info(f"Начало генерации рекомендаций для пользователя {user_id} по запросу: '{user_query}'")

            user_preferences = self.db.get_user_preferences(user_id)
            user_ratings = self.db.get_user_ratings(user_id)

            context_for_llm = ""
            if user_preferences:
                context_for_llm += "\n\nПользовательские предпочтения: " + \
                                   ", ".join(
                                       [f"{p['preference_type']}: {p['preference_value']}" for p in user_preferences])
            if user_ratings:
                high_rated_movies = [
                    f"«{r['title']}» ({r['rating']}/10)" for r in user_ratings if r['rating'] >= 8
                ]
                if high_rated_movies:
                    context_for_llm += "\n\nФильмы, высоко оцененные пользователем: " + ", ".join(
                        high_rated_movies[:5])

            excluded_movie_ids = {r['movie_id'] for r in user_ratings}
            excluded_titles_from_db = []
            for movie_id in excluded_movie_ids:
                movie_details = self.db.get_movie(movie_id)
                if movie_details:
                    excluded_titles_from_db.append(movie_details.get('title'))

            if excluded_titles_from_db:
                context_for_llm += "\n\nНЕ рекомендуй эти фильмы (уже известны пользователю): " + ", ".join(
                    excluded_titles_from_db[:10])

            detected_language = await self.translator_agent.detect_language(user_query)
            query_for_llm = user_query + context_for_llm

            llm_candidate_response = await self.llm_generator.generate(
                prompt=query_for_llm,
                system_prompt=self.initial_system_prompt
            )
            logger.info(f"LLM candidate response: {llm_candidate_response}")

            candidate_titles_with_years = await self._extract_movie_titles_from_llm_response(llm_candidate_response)
            if not candidate_titles_with_years:
                logger.warning("Не удалось извлечь названия фильмов из ответа LLM.")
                return {
                    "error": "К сожалению, LLM не смогла сгенерировать понятные названия фильмов. "
                             "Пожалуйста, попробуйте перефразировать ваш запрос.",
                    "llm_response": "Я не смог найти фильмы по вашему запросу.",
                    "recommendations": []
                }

            valid_recommendations: List[Dict[str, Any]] = []
            final_recommended_movie_titles: List[str] = []

            for title_ru, year in candidate_titles_with_years[:5]:
                title_for_tmdb_search = title_ru
                if isinstance(detected_language, str) and detected_language.lower() == 'ru':
                    translated_title = await self.translator_agent.translate_to_english(title_ru)
                    if self.translator_agent.is_translation_different(title_ru, translated_title):
                        title_for_tmdb_search = translated_title
                        logger.info(
                            f"Translated Russian title '{title_ru}' to English for TMDB search: '{translated_title}'")
                    else:
                        logger.warning(
                            f"Translation to English for TMDB failed or returned same text for '{title_ru}'. Using original.")

                logger.info(f"Searching TMDB for movie: '{title_for_tmdb_search}' (original: '{title_ru}')")

                movie_data = await self.tmdb_agent.enrich_query(title_for_tmdb_search)

                if movie_data:
                    is_relevant = await self._validate_movie_relevance(user_query, title_ru, movie_data)

                    if is_relevant:
                        db_movie_id = self.db.get_movie_id_by_tmdb_id(movie_data.get("tmdb_id"))
                        if not db_movie_id:
                            db_movie_id = self.db.add_movie(movie_data)
                            logger.info(f"Added movie '{movie_data.get('title')}' to DB as ID {db_movie_id}")
                        else:
                            logger.info(f"Movie '{movie_data.get('title')}' already in DB as ID {db_movie_id}")

                        if db_movie_id:
                            self.db.add_user_history(user_id, db_movie_id, "recommendation")
                            logger.info(f"Saved recommendation history for user {user_id}, movie {db_movie_id}")

                        valid_recommendations.append(movie_data)
                        tmdb_release_year_for_display = int(movie_data.get('release_date', '')[:4]) if movie_data.get(
                            'release_date') else 'N/A'

                        escaped_title = self._escape_markdown_v2(movie_data.get('title'))
                        final_recommended_movie_titles.append(
                            f"**{escaped_title}** ({tmdb_release_year_for_display})")
                    else:
                        logger.warning(
                            f"Movie '{movie_data.get('title')}' deemed not relevant to original query: '{user_query[:50]}...' or LLM suggestion. Skipping.")
                else:
                    logger.warning(
                        f"Could not find or enrich movie data for candidate title: '{title_for_tmdb_search}' (original: '{title_ru}'). Skipping.")

            if valid_recommendations:
                final_llm_prompt = (
                    f"Вот список фильмов, которые я для вас подобрал: "
                    f"{', '.join(final_recommended_movie_titles)}."
                    f"Напиши короткий, дружелюбный текст, рекомендуя эти фильмы, "
                    f"как будто ты только что их нашел специально для пользователя. "
                    f"Не используй общие фразы типа 'Вот что я могу порекомендовать'. "
                    f"Просто представь список фильмов в естественной манере."
                    f"Упоминай только те фильмы, которые были предоставлены."
                )

                final_llm_response = await self.llm_generator.generate(
                    prompt=final_llm_prompt,
                    system_prompt=self.final_system_prompt,
                    temperature=0.7
                )
            else:
                final_llm_response = (
                    "К сожалению, я не смог найти подходящих фильмов по вашему запросу. "
                    "Пожалуйста, попробуйте перефразировать или быть более конкретным."
                )
                logger.info("No valid recommendations found after TMDB search and validation.")

            return {
                "llm_response": final_llm_response,
                "recommendations": valid_recommendations
            }

        except Exception as e:
            logger.error(f"Глобальная ошибка в generate_recommendations для запроса '{user_query}': {e}", exc_info=True)
            return {
                "error": "Произошла непредвиденная ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз."}
