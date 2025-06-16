import os
import json
import logging
import google.generativeai as genai
from typing import List, Dict, Any, Optional
import requests
import re
from database import MovieDatabase
import asyncio
import time
import random
from urllib.parse import urlparse
import httpx
import ssl

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class RecommendationEngine:
    def __init__(self, api_key: str, tmdb_api_key: str, db: MovieDatabase):
        """
        Initialize the recommendation engine.

        Args:
            api_key: Google Gemini API key
            tmdb_api_key: TMDB API key
            db: MovieDatabase instance
        """
        self.api_key = api_key
        self.tmdb_api_key = tmdb_api_key
        self.db = db
        self.tmdb_base_url = "https://api.themoviedb.org/3"

        # Configure Google Generative AI
        genai.configure(api_key=api_key)

        # For proxy fallback
        self.use_proxy = False
        self.proxies = []
        self.current_proxy = None

        # Get available models and select appropriate model
        try:
            # Преобразуем генератор в список
            self.models = list(genai.list_models())
            logger.info(f"Found {len(self.models)} available models")

            # Приоритет моделей для выбора - от простых к сложным
            model_preference = [
                "gemini-1.5-flash-8b",  # Самая легкая модель
                "gemini-1.5-flash",  # Легкая модель
                "gemini-1.0-pro-vision",
                "gemini-1.5-pro",  # Мощная модель
            ]

            # Сначала попробуем найти модель по приоритетному списку
            selected_model = None
            for preferred_model in model_preference:
                for model in self.models:
                    if preferred_model in model.name and hasattr(model,
                                                                 'supported_generation_methods') and model.supported_generation_methods and "generateContent" in model.supported_generation_methods:
                        selected_model = model.name
                        logger.info(f"Selected model from priority list: {selected_model}")
                        break
                if selected_model:
                    break

            # Если не нашли модель из списка приоритетов, возьмем первую flash модель или любую другую
            if not selected_model:
                flash_models = [m for m in self.models if "flash" in m.name.lower()
                                and hasattr(m, 'supported_generation_methods')
                                and m.supported_generation_methods
                                and "generateContent" in m.supported_generation_methods]

                if flash_models:
                    selected_model = flash_models[0].name
                    logger.info(f"Using flash model: {selected_model}")
                else:
                    # Последняя попытка - любая модель с поддержкой generateContent
                    content_models = [m for m in self.models
                                      if hasattr(m, 'supported_generation_methods')
                                      and m.supported_generation_methods
                                      and "generateContent" in m.supported_generation_methods]

                    if content_models:
                        selected_model = content_models[0].name
                        logger.info(f"Using available model: {selected_model}")
                    else:
                        # Если совсем ничего не нашли, используем стандартную модель
                        selected_model = "gemini-1.5-flash"
                        logger.warning(f"No suitable models found, defaulting to: {selected_model}")

            self.model = genai.GenerativeModel(selected_model)
            logger.info(f"Successfully initialized model: {selected_model}")

        except Exception as e:
            logger.error(f"Error selecting model: {str(e)}")
            # Fallback to a lightweight model
            self.model = genai.GenerativeModel("gemini-1.5-flash")
            logger.info("Using default model: gemini-1.5-flash due to error")

    async def _get_free_proxies(self) -> List[str]:
        """Get a list of free proxies to try."""
        try:
            # Try several free proxy sources
            proxy_sources = [
                "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
                "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
                "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"
            ]

            all_proxies = []
            async with httpx.AsyncClient(timeout=5.0) as client:
                for source in proxy_sources:
                    try:
                        response = await client.get(source)
                        if response.status_code == 200:
                            proxies = [f"http://{line.strip()}" for line in response.text.splitlines() if line.strip()]
                            all_proxies.extend(proxies)
                            logger.info(f"Found {len(proxies)} proxies from {source}")
                    except Exception as e:
                        logger.warning(f"Failed to get proxies from {source}: {e}")

            # Shuffle to distribute load
            random.shuffle(all_proxies)
            return all_proxies[:25]  # Limit to 25 to avoid excessive retries
        except Exception as e:
            logger.error(f"Error getting free proxies: {e}")
            return []

    async def _test_proxy(self, proxy: str) -> bool:
        """Test if a proxy works with Google API."""
        try:
            parsed = urlparse(proxy)
            if not parsed.scheme or not parsed.netloc:
                return False

            # Try a simple HEAD request to Google
            async with httpx.AsyncClient(proxies={"http://": proxy, "https://": proxy}, timeout=5.0) as client:
                response = await client.head("https://generativelanguage.googleapis.com/", timeout=3.0)
                return response.status_code < 400
        except Exception:
            return False

    async def _setup_proxy_if_needed(self):
        """Set up proxy if we haven't already and need one."""
        if self.use_proxy and not self.proxies:
            logger.info("Setting up proxy fallback due to location restrictions")
            self.proxies = await self._get_free_proxies()
            if not self.proxies:
                logger.warning("No working proxies found")

    async def _get_working_proxy(self) -> Optional[str]:
        """Get a working proxy or None if none available."""
        await self._setup_proxy_if_needed()

        if not self.proxies:
            return None

        # Try proxies until we find a working one
        max_attempts = min(5, len(self.proxies))
        for _ in range(max_attempts):
            if not self.proxies:
                return None

            proxy = self.proxies.pop(0)
            if await self._test_proxy(proxy):
                logger.info(f"Found working proxy: {proxy}")
                return proxy

        return None

    async def generate_recommendations(self, user_query: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate movie recommendations based on user query using Google Gemini.

        Args:
            user_query: User's request for recommendations
            user_id: Optional Telegram user ID for personalization

        Returns:
            Dictionary containing recommendation results
        """
        try:
            # Get list of already rated movies to exclude them
            excluded_movies = []
            if user_id:
                user_ratings = self.db.get_user_ratings(user_id)
                excluded_movies = [rating['title'] for rating in user_ratings]

            # НОВОЕ: Обогащаем запрос реальными данными из TMDB
            logger.info("Enriching query with TMDB data...")
            enriched_user_query = await self._enrich_query_with_tmdb_data(user_query)

            # Enhance query with user preferences if user_id is provided (but limit influence)
            enhanced_query = enriched_user_query
            if user_id:
                user_preferences = self.db.get_user_preferences(user_id)
                if user_preferences:
                    # Группируем предпочтения по типам и ограничиваем количество
                    pref_by_type = {}
                    for pref in user_preferences:
                        pref_type = pref['preference_type']
                        if pref_type not in pref_by_type:
                            pref_by_type[pref_type] = []
                        pref_by_type[pref_type].append(pref['preference_value'])
                    
                    # Ограничиваем влияние предпочтений - берем только 2-3 элемента каждого типа
                    limited_preferences = []
                    for pref_type, values in pref_by_type.items():
                        # Берем только 2 самых частых предпочтения для каждого типа
                        limited_values = values[:2]
                        for value in limited_values:
                            limited_preferences.append(f"{pref_type}: {value}")
                    
                    if limited_preferences:
                        preferences_text = " ".join(limited_preferences)
                        enhanced_query = f"{enriched_user_query}\n\nUser preferences (consider moderately): {preferences_text}"

                # Also include user ratings if available (but limit to best rated movies only)
                if user_ratings:
                    # Берем только фильмы с оценкой 8+ и ограничиваем до 3
                    high_rated = [rating for rating in user_ratings if rating['rating'] >= 8][:3]
                    if high_rated:
                        ratings_text = " ".join([f"{rating['title']}: {rating['rating']}/10"
                                                 for rating in high_rated])
                        enhanced_query = f"{enhanced_query}\n\nUser's favorite movies: {ratings_text}"

            # Add instruction to avoid already rated movies
            if excluded_movies:
                excluded_text = ", ".join(excluded_movies[:10])  # Limit to avoid too long prompt
                enhanced_query = f"{enhanced_query}\n\nDO NOT recommend these already rated movies: {excluded_text}"

            # Generate recommendations using Gemini
            system_prompt = """Ты - помощник по рекомендации фильмов. При рекомендации фильмов:

ВАЖНО:
1. Указывай ТОЛЬКО реальные существующие фильмы с точными названиями
2. Обязательно указывай год выпуска фильма в скобках после названия
3. Проверяй точность названий - не выдумывай фильмы
4. Форматируй названия как: **"Точное название фильма" (Год)**
5. Рекомендуй 3-5 разнообразных фильмов
6. Избегай фильмов одного режиссера или франшизы, если не просят конкретно
7. Предпочитай разнообразие жанров, годов и стилей
8. Кратко объясни, почему каждый фильм подходит под запрос
9. ИСПОЛЬЗУЙ предоставленную информацию из TMDB для точных рекомендаций
10. Если в запросе есть информация о конкретных актерах/режиссерах из TMDB, обязательно учитывай их фильмографию

Формат ответа:
Вступительная фраза...

**"Название фильма 1" (Год)**. Краткое объяснение почему подходит.

**"Название фильма 2" (Год)**. Краткое объяснение почему подходит.

И так далее...

Отвечай на русском языке."""

            full_prompt = f"{system_prompt}\n\nПожалуйста, порекомендуй фильмы на основе этого запроса: {enhanced_query}"

            # Используем более низкие настройки для меньшего потребления токенов
            generation_config = {
                "temperature": 0.7,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 800,  # Снижено для экономии токенов
            }

            # Базовые настройки безопасности
            safety_settings = [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                }
            ]

            # Добавляем повторные попытки при ошибке превышения квоты
            max_retries = 3
            retry_delay = 2  # секунды

            for attempt in range(max_retries):
                try:
                    # If we encountered location restrictions, try with proxy
                    if self.use_proxy:
                        # Get a working proxy
                        proxy = await self._get_working_proxy()
                        if proxy:
                            # Can't directly use proxy with Google client library,
                            # so we'll need to use a raw API request

                            # This would require implementation of a custom function to call the API with proxy
                            # For demonstration, we'll show an error that we need a custom solution
                            error_msg = "Прокси-решение требует custom-реализации. Рекомендуется использовать VPN или другой способ доступа к API."
                            logger.warning(error_msg)
                            return {
                                "original_query": user_query,
                                "error": "Location not supported",
                                "recommendations": [],
                                "llm_response": f"""Извините, но API Google Gemini недоступно в вашем регионе.

Рекомендуемые решения:
1. Используйте VPN для доступа к API
2. Используйте другой API ключ, полученный через аккаунт в поддерживаемом регионе
3. Обратитесь к администратору для настройки прокси-сервера

В качестве временной альтернативы, вот некоторые популярные фильмы:
1. "Интерстеллар" (2014) - научно-фантастический фильм о космических путешествиях
2. "Зеленая миля" (1999) - драма о надзирателе в тюрьме и заключенном с необычными способностями
3. "Остров проклятых" (2010) - психологический триллер с неожиданной концовкой
4. "Бойцовский клуб" (1999) - культовый фильм о тайном обществе
5. "Начало" (2010) - фильм о проникновении в сны людей"""
                            }

                    # Without proxy, try regular API call
                    response = self.model.generate_content(
                        full_prompt,
                        generation_config=generation_config,
                        safety_settings=safety_settings
                    )
                    llm_response = response.text
                    break
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"API error (attempt {attempt + 1}/{max_retries}): {error_message}")

                    if "429" in error_message and attempt < max_retries - 1:
                        logger.warning(
                            f"Rate limit hit, retrying in {retry_delay} seconds... ({attempt + 1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Увеличиваем задержку с каждой попыткой
                    elif "403" in error_message or "User location is not supported" in error_message:
                        # Enable proxy mode for future calls
                        self.use_proxy = True
                        logger.warning("Location restriction detected, enabling proxy fallback")

                        # If we're on the last attempt, return helpful error
                        if attempt == max_retries - 1:
                            error_info = """Доступ к API запрещен из-за географических ограничений.

Рекомендуется:
1. Использовать VPN для доступа к API
2. Использовать другой API ключ из поддерживаемого региона
3. Обратитесь к администратору для настройки прокси-сервера"""
                            logger.error(error_info)

                            # Return fallback recommendations
                            return {
                                "original_query": user_query,
                                "error": "Location not supported",
                                "recommendations": [],
                                "llm_response": f"""Извините, но API Google Gemini недоступно в вашем регионе.

Рекомендуемые решения:
1. Используйте VPN для доступа к API
2. Используйте другой API ключ, полученный через аккаунт в поддерживаемом регионе
3. Обратитесь к администратору для настройки прокси-сервера

В качестве временной альтернативы, вот некоторые популярные фильмы по запросу "{user_query}":
1. "Интерстеллар" (2014) - научно-фантастический фильм о космических путешествиях
2. "Зеленая миля" (1999) - драма о надзирателе в тюрьме и заключенном с необычными способностями
3. "Остров проклятых" (2010) - психологический триллер с неожиданной концовкой
4. "Бойцовский клуб" (1999) - культовый фильм о тайном обществе
5. "Начало" (2010) - фильм о проникновении в сны людей"""
                            }
                    else:
                        raise
            else:
                # Если все попытки не удались, возвращаем ошибку
                raise Exception("Превышена квота API. Попробуйте позже.")

            # Parse the LLM response to extract movie titles
            movie_titles = self._extract_movie_titles(llm_response)

            # Fetch additional details for each movie from TMDB
            detailed_recommendations = []
            validation_summary = {
                'total_extracted': len(movie_titles),
                'excluded_already_rated': 0,
                'excluded_validation_failed': 0,
                'excluded_not_found': 0,
                'included': 0
            }
            
            excluded_movies_info = []  # Для отслеживания исключенных фильмов
            
            for title in movie_titles:
                # Skip movies that user has already rated
                if title in excluded_movies:
                    logger.info(f"Skipping already rated movie: {title}")
                    validation_summary['excluded_already_rated'] += 1
                    continue
                    
                movie_details = await self._get_movie_details_from_tmdb(title)
                if not movie_details:
                    logger.info(f"Movie not found in TMDB: {title}")
                    validation_summary['excluded_not_found'] += 1
                    excluded_movies_info.append(f'"{title}" - не найден в TMDB')
                    continue
                
                # Double-check movie isn't in excluded list (by different title variations)
                movie_title = movie_details.get('title', '')
                original_title = movie_details.get('original_title', '')
                
                is_excluded = False
                for excluded in excluded_movies:
                    if (excluded.lower() in movie_title.lower() or 
                        movie_title.lower() in excluded.lower() or
                        (original_title and (excluded.lower() in original_title.lower() or 
                                            original_title.lower() in excluded.lower()))):
                        is_excluded = True
                        break
                
                if not is_excluded:
                    # НОВАЯ ВАЛИДАЦИЯ: Проверяем соответствие фильма запросу
                    # Используем обогащенный запрос для более точной валидации
                    is_valid = await self._validate_movie_match(movie_details, enriched_user_query, title)
                    
                    if is_valid:
                        detailed_recommendations.append(movie_details)
                        validation_summary['included'] += 1

                        # Save movie to database if not already present
                        existing_movie = self.db.get_movie_by_tmdb_id(movie_details.get('tmdb_id'))
                        if not existing_movie:
                            self.db.add_movie(movie_details)
                    else:
                        logger.info(f"Skipping invalid movie: '{movie_title}' - doesn't match user request")
                        validation_summary['excluded_validation_failed'] += 1
                        excluded_movies_info.append(f'"{movie_title}" - не соответствует запросу')
                else:
                    logger.info(f"Skipping excluded movie variant: {movie_title}")
                    validation_summary['excluded_already_rated'] += 1

            # НОВАЯ ЛОГИКА: Повторная генерация при недостатке валидных рекомендаций
            retry_count = 0
            max_retries = 2
            
            while (validation_summary['included'] < 2 and 
                   validation_summary['excluded_validation_failed'] > 0 and 
                   retry_count < max_retries):
                
                retry_count += 1
                logger.info(f"Attempting retry {retry_count} due to insufficient valid recommendations")
                
                # Создаем список исключенных фильмов для ИИ
                excluded_list = ", ".join(excluded_movies_info[-5:])  # Последние 5 исключенных
                
                # Улучшенный промпт для повторной генерации
                retry_prompt = f"""Первая генерация дала неточные рекомендации. Некоторые фильмы были исключены: {excluded_list}

ВАЖНО: Проверь точность информации!
- НЕ выдумывай участие актеров в фильмах, где они не снимались
- Указывай ТОЛЬКО реальные факты об актерах и режиссерах
- Если не уверен в участии актера в фильме - НЕ рекомендуй его

ПОВТОРНЫЙ ЗАПРОС: {enhanced_query}

Порекомендуй 3-4 ДРУГИХ фильма (не из исключенных), проверив точность информации об актерах/режиссерах."""

                try:
                    retry_response = self.model.generate_content(
                        retry_prompt,
                        generation_config=generation_config,
                        safety_settings=safety_settings
                    )
                    retry_llm_response = retry_response.text
                    
                    # Извлекаем новые рекомендации
                    retry_movie_titles = self._extract_movie_titles(retry_llm_response)
                    logger.info(f"Retry {retry_count} extracted {len(retry_movie_titles)} movies: {retry_movie_titles}")
                    
                    # Обрабатываем новые рекомендации
                    for title in retry_movie_titles:
                        # Избегаем дублирования уже обработанных фильмов
                        already_processed = any(title.lower() in processed_title.lower() 
                                              for processed_title in movie_titles)
                        if already_processed:
                            continue
                            
                        if title in excluded_movies:
                            continue
                            
                        movie_details = await self._get_movie_details_from_tmdb(title)
                        if not movie_details:
                            excluded_movies_info.append(f'"{title}" - не найден в TMDB (retry {retry_count})')
                            continue
                        
                        movie_title = movie_details.get('title', '')
                        
                        # Проверка на дубликаты в уже найденных рекомендациях
                        is_duplicate = any(rec.get('title', '').lower() == movie_title.lower() 
                                         for rec in detailed_recommendations)
                        if is_duplicate:
                            continue
                        
                        is_valid = await self._validate_movie_match(movie_details, enriched_user_query, title)
                        
                        if is_valid:
                            detailed_recommendations.append(movie_details)
                            validation_summary['included'] += 1
                            movie_titles.append(title)  # Добавляем к общему списку
                            logger.info(f"Added valid movie from retry {retry_count}: {movie_title}")

                            existing_movie = self.db.get_movie_by_tmdb_id(movie_details.get('tmdb_id'))
                            if not existing_movie:
                                self.db.add_movie(movie_details)
                                
                            # Если набрали достаточно рекомендаций, прерываем
                            if validation_summary['included'] >= 3:
                                break
                        else:
                            validation_summary['excluded_validation_failed'] += 1
                            excluded_movies_info.append(f'"{movie_title}" - не соответствует запросу (retry {retry_count})')
                    
                    # Обновляем LLM ответ с учетом повторной генерации
                    if retry_count == 1:
                        llm_response += f"\n\n📝 Дополнительные рекомендации (после проверки):\n{retry_llm_response}"
                    
                except Exception as e:
                    logger.error(f"Error during retry {retry_count}: {e}")
                    break

            # Логируем финальную статистику валидации
            logger.info(f"Final validation summary after {retry_count} retries: {validation_summary}")
            
            # Если после повторных попыток все еще мало фильмов, добавляем пояснение
            if validation_summary['included'] < 2 and validation_summary['excluded_validation_failed'] > 0:
                additional_info = f"\n\n⚠️ После {retry_count} попыток улучшить рекомендации, некоторые фильмы все еще были исключены из-за неточной информации (найдено {validation_summary['excluded_validation_failed']} несоответствий)."
                llm_response += additional_info
            elif retry_count > 0 and validation_summary['included'] >= 2:
                additional_info = f"\n\n✅ Рекомендации улучшены после дополнительной проверки (попыток: {retry_count})."
                llm_response += additional_info

            return {
                "original_query": user_query,
                "llm_response": llm_response,
                "recommendations": detailed_recommendations
            }

        except Exception as e:
            error_message = str(e)
            logger.error(f"Error generating recommendations: {error_message}")

            # Формируем понятное сообщение об ошибке
            user_friendly_message = error_message

            if "403" in error_message or "User location is not supported" in error_message:
                # Set proxy mode for future requests
                self.use_proxy = True

                user_friendly_message = """Доступ к Google Gemini API запрещен из вашего региона.

Рекомендуемые решения:
1. Используйте VPN для доступа к API
2. Используйте другой API ключ из поддерживаемого региона
3. Обратитесь к администратору для настройки альтернативного API

В качестве временной альтернативы, вот некоторые популярные фильмы:
1. "Интерстеллар" (2014) - научно-фантастический фильм о космических путешествиях
2. "Зеленая миля" (1999) - драма о надзирателе в тюрьме и заключенном с необычными способностями
3. "Остров проклятых" (2010) - психологический триллер с неожиданной концовкой
4. "Бойцовский клуб" (1999) - культовый фильм о тайном обществе
5. "Начало" (2010) - фильм о проникновении в сны людей"""
            elif "429" in error_message:
                user_friendly_message = "Превышен лимит запросов к API. Пожалуйста, попробуйте позже."
            elif "404" in error_message:
                user_friendly_message = "Модель не найдена. Возможно, выбранная модель недоступна для вашего API ключа."

            return {
                "original_query": user_query,
                "error": error_message,
                "recommendations": [],
                "llm_response": f"Извините, произошла ошибка при получении рекомендаций: {user_friendly_message}"
            }

    def _extract_movie_titles(self, llm_response: str) -> List[str]:
        """
        Extract movie titles from the LLM response.

        Args:
            llm_response: Text response from Gemini

        Returns:
            List of extracted movie titles
        """
        try:
            # Улучшенные паттерны для извлечения названий фильмов
            # Ищем паттерны типа **"Название фильма" (Год)** или "Название фильма" (Год)
            title_patterns = [
                r'\*\*"([^"]+)"\s*\((\d{4})\)\*\*',  # **"Title" (Year)**
                r'"([^"]+)"\s*\((\d{4})\)',           # "Title" (Year)
                r'\*\*([^*]+)\*\*\s*\((\d{4})\)',    # **Title** (Year)
                r'«([^»]+)»\s*\((\d{4})\)',           # «Title» (Year) - русские кавычки
                r'"([^"]+)"\s*\((\d{4})\)',           # "Title" (Year) - обычные кавычки
            ]
            
            extracted_titles = []
            
            # Пробуем каждый паттерн
            for pattern in title_patterns:
                matches = re.findall(pattern, llm_response)
                for match in matches:
                    if len(match) == 2:  # title, year
                        title, year = match
                        full_title = f"{title.strip()} ({year})"
                        if full_title not in extracted_titles:
                            extracted_titles.append(full_title)
            
            # Если нашли фильмы с годами, возвращаем их
            if extracted_titles:
                logger.info(f"Extracted titles with years: {extracted_titles}")
                return extracted_titles
            
            # Если не нашли с годами, ищем просто названия в кавычках/звездочках
            simple_patterns = [
                r'\*\*"([^"]+)"\*\*',     # **"Title"**
                r'"([^"]+)"',             # "Title"
                r'\*\*([^*]+)\*\*',       # **Title**
                r'«([^»]+)»',             # «Title»
            ]
            
            for pattern in simple_patterns:
                matches = re.findall(pattern, llm_response)
                for title in matches:
                    title = title.strip()
                    # Фильтруем слишком короткие или явно не являющиеся названиями строки
                    if len(title) > 3 and not title.lower() in ['год', 'фильм', 'года', 'this', 'that']:
                        if title not in extracted_titles:
                            extracted_titles.append(title)
            
            if extracted_titles:
                logger.info(f"Extracted simple titles: {extracted_titles}")
                return extracted_titles

            # Если и это не сработало, используем LLM для извлечения (более затратно)
            extraction_prompt = f"""Внимательно проанализируй текст и извлеки ТОЧНЫЕ названия фильмов, которые упоминаются в рекомендациях.
            
Верни результат в виде JSON массива строк в формате 'Название (Год)' или просто 'Название', если год не указан.
Не выдумывай названия - используй только те, что есть в тексте.

Текст для анализа:
{llm_response}

Верни только JSON массив, ничего больше."""

            # Более экономные настройки
            generation_config = {
                "temperature": 0.1,  # Низкая температура для точности
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 300,  # Меньше токенов
            }

            # Добавляем повторные попытки при ошибке превышения квоты
            max_retries = 2
            retry_delay = 1  # секунды

            for attempt in range(max_retries):
                try:
                    response = self.model.generate_content(
                        extraction_prompt,
                        generation_config=generation_config
                    )
                    extraction_result = response.text
                    break
                except Exception as e:
                    if "429" in str(e) and attempt < max_retries - 1:
                        logger.warning(f"Rate limit hit during extraction, retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.warning(f"LLM extraction failed: {e}, using regex fallback")
                        return []
            else:
                return []

            # Try to parse JSON from the response
            try:
                # Look for JSON array in the response
                json_match = re.search(r'\[.*\]', extraction_result, re.DOTALL)
                if json_match:
                    titles = json.loads(json_match.group(0))
                    logger.info(f"LLM extracted titles: {titles}")
                    return titles

                # If no JSON array found, try to extract titles with regex
                titles = re.findall(r'"([^"]+)"', extraction_result)
                if titles:
                    logger.info(f"LLM fallback extracted titles: {titles}")
                    return titles

                return []

            except json.JSONDecodeError:
                logger.warning("Failed to parse LLM JSON response")
                return []

        except Exception as e:
            logger.error(f"Error extracting movie titles: {e}")
            return []

    # Функция для нормализации текста - вынесем ее на уровень класса
    def _normalize_text(self, text):
        if not text:
            return ""
        # Преобразуем в строку, если это не строка
        if not isinstance(text, str):
            try:
                return str(text)
            except:
                return ""
        return text

    async def _get_movie_details_from_tmdb(self, movie_title: str) -> Optional[Dict[str, Any]]:
        """
        Get movie details from TMDB API.

        Args:
            movie_title: Movie title to search for

        Returns:
            Dictionary with movie details or None if not found
        """
        try:
            # Extract year from title if present
            import re
            year_match = re.search(r'\((\d{4})\)', movie_title)
            year = year_match.group(1) if year_match else None

            # Clean title by removing year and extra formatting
            clean_title = re.sub(r'\s*\(\d{4}\)', '', movie_title).strip()
            clean_title = clean_title.strip('"«»*')  # Remove quotes and formatting
            
            logger.info(f"Searching for movie: '{clean_title}' (year: {year})")

            # Use httpx instead of requests for better SSL handling
            async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
                # Search for movie in TMDB
                search_url = f"{self.tmdb_base_url}/search/movie"
                params = {
                    "api_key": self.tmdb_api_key,
                    "query": clean_title,
                    "language": "ru-RU"
                }
                if year:
                    params["year"] = year

                # Try up to 3 times with increasing timeout
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = await client.get(search_url, params=params)
                        response.raise_for_status()
                        search_results = response.json()
                        break
                    except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout, 
                            httpx.ReadTimeout, ssl.SSLError) as e:
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # Exponential backoff
                            logger.warning(f"TMDB search attempt {attempt+1} failed: {e}. Retrying in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(f"All TMDB search attempts failed: {e}")
                            return None
                else:
                    # All attempts failed
                    return None

                if not search_results.get('results'):
                    logger.warning(f"No TMDB results found for movie: {movie_title}")
                    # Попробуем поиск без года, если был указан год
                    if year:
                        logger.info(f"Retrying search without year for: {clean_title}")
                        params_no_year = {
                            "api_key": self.tmdb_api_key,
                            "query": clean_title,
                            "language": "ru-RU"
                        }
                        try:
                            response = await client.get(search_url, params=params_no_year)
                            response.raise_for_status()
                            search_results = response.json()
                        except:
                            logger.error(f"Retry search also failed for: {clean_title}")
                            return None
                    
                    if not search_results.get('results'):
                        return None

                # Find the best match
                best_match = None
                best_score = 0
                
                for movie in search_results['results'][:5]:  # Check top 5 results
                    movie_title_tmdb = movie.get('title', '').lower()
                    original_title_tmdb = movie.get('original_title', '').lower()
                    release_date = movie.get('release_date', '')
                    movie_year = release_date[:4] if release_date else None
                    
                    # Calculate similarity score
                    score = 0
                    clean_title_lower = clean_title.lower()
                    
                    # Точное совпадение названия
                    if clean_title_lower == movie_title_tmdb or clean_title_lower == original_title_tmdb:
                        score += 100
                    
                    # Частичное совпадение названия
                    elif clean_title_lower in movie_title_tmdb or movie_title_tmdb in clean_title_lower:
                        score += 80
                    elif clean_title_lower in original_title_tmdb or original_title_tmdb in clean_title_lower:
                        score += 75
                    
                    # Совпадение по ключевым словам
                    clean_words = set(clean_title_lower.split())
                    title_words = set(movie_title_tmdb.split())
                    original_words = set(original_title_tmdb.split())
                    
                    # Подсчет общих слов
                    common_with_title = len(clean_words.intersection(title_words))
                    common_with_original = len(original_words.intersection(clean_words))
                    max_common = max(common_with_title, common_with_original)
                    
                    if max_common > 0:
                        score += max_common * 20
                    
                    # Бонус за совпадение года
                    if year and movie_year == year:
                        score += 50
                    
                    # Штраф за большое различие в году
                    if year and movie_year and abs(int(year) - int(movie_year)) > 2:
                        score -= 30
                    
                    logger.info(f"Movie: '{movie_title_tmdb}' ({movie_year}) - Score: {score}")
                    
                    if score > best_score:
                        best_score = score
                        best_match = movie

                # Если лучший результат имеет слишком низкий рейтинг, не возвращаем его
                if best_score < 40:
                    logger.warning(f"Best match score too low ({best_score}) for: {movie_title}")
                    return None

                if not best_match:
                    logger.warning(f"No suitable match found for: {movie_title}")
                    return None

                logger.info(f"Selected movie: '{best_match.get('title')}' ({best_match.get('release_date', '')[:4]}) with score: {best_score}")

                # Get detailed info for the best match
                movie_id = best_match['id']
                details_url = f"{self.tmdb_base_url}/movie/{movie_id}"
                params = {
                    "api_key": self.tmdb_api_key,
                    "language": "ru-RU",
                    "append_to_response": "credits,similar"
                }

                # Try up to 3 times with increasing timeout
                for attempt in range(max_retries):
                    try:
                        response = await client.get(details_url, params=params)
                        response.raise_for_status()
                        details = response.json()
                        break
                    except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout, 
                            httpx.ReadTimeout, ssl.SSLError) as e:
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # Exponential backoff
                            logger.warning(f"TMDB details attempt {attempt+1} failed: {e}. Retrying in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(f"All TMDB details attempts failed: {e}")
                            return None
                else:
                    # All attempts failed
                    return None

                # Extract directors and actors
                directors = []
                actors = []

                if 'credits' in details:
                    # Извлекаем режиссеров и убеждаемся, что они сохраняются как строки
                    for crew in details['credits'].get('crew', []):
                        if crew.get('job') == 'Director':
                            director_name = self._normalize_text(crew.get('name', ''))
                            if director_name:
                                directors.append(director_name)

                    # Извлекаем актеров и убеждаемся, что они сохраняются как строки
                    for cast in details['credits'].get('cast', []):
                        if cast.get('order', 999) < 5:  # Get top 5 billed actors
                            actor_name = self._normalize_text(cast.get('name', ''))
                            if actor_name:
                                actors.append(actor_name)

                # Extract genres as strings
                genres = []
                for genre in details.get('genres', []):
                    genre_name = self._normalize_text(genre.get('name', ''))
                    if genre_name:
                        genres.append(genre_name)

                # Create movie details dictionary with normalized text
                movie_data = {
                    'tmdb_id': details['id'],
                    'title': self._normalize_text(details['title']),
                    'original_title': self._normalize_text(details.get('original_title')),
                    'overview': self._normalize_text(details.get('overview')),
                    'release_date': self._normalize_text(details.get('release_date')),
                    'poster_path': self._normalize_text(details.get('poster_path')),
                    'genres': genres,
                    'runtime': details.get('runtime'),
                    'vote_average': details.get('vote_average'),
                    'vote_count': details.get('vote_count'),
                    'popularity': details.get('popularity'),
                    'directors': directors,
                    'actors': actors
                }

                logger.info(f"Successfully found movie: {movie_data['title']} ({movie_data['release_date'][:4] if movie_data['release_date'] else 'N/A'})")
                return movie_data

        except Exception as e:
            logger.error(f"Error getting movie details from TMDB: {e}")
            return None

    async def process_user_feedback(self, user_id: int, movie_id: int, rating: int) -> bool:
        """
        Process user feedback on a movie recommendation.

        Args:
            user_id: Telegram user ID
            movie_id: Database ID of the movie
            rating: User rating (1-10)

        Returns:
            True if feedback was processed successfully, False otherwise
        """
        try:
            # Save rating to database
            success = self.db.add_user_rating(user_id, movie_id, rating)

            # Add to user history
            if success:
                self.db.add_user_history(user_id, movie_id, f"rated_{rating}")

            # Extract movie details for preference learning (only for exceptional ratings)
            movie = self.db.get_movie_by_tmdb_id(movie_id)
            if movie and rating >= 9:  # Only learn from exceptional ratings (9-10)
                # Get current user preferences to avoid duplicates and limit quantity
                current_preferences = self.db.get_user_preferences(user_id)
                
                # Count current preferences by type
                pref_counts = {}
                for pref in current_preferences:
                    pref_type = pref['preference_type']
                    pref_counts[pref_type] = pref_counts.get(pref_type, 0) + 1
                
                # Add genre preferences (limit to 5 per type)
                if movie.get('genres') and pref_counts.get('genre', 0) < 5:
                    # Add only the first genre to avoid overwhelming preferences
                    genre = movie['genres'][0] if movie['genres'] else None
                    if genre:
                        # Check if this genre is already in preferences
                        existing_genres = [p['preference_value'] for p in current_preferences 
                                         if p['preference_type'] == 'genre']
                        if genre not in existing_genres:
                            self.db.add_user_preference(user_id, 'genre', genre)

                # Add director preferences (limit to 3 per type, only for 10/10 ratings)
                if movie.get('directors') and rating == 10 and pref_counts.get('director', 0) < 3:
                    # Add only the first director
                    director = movie['directors'][0] if movie['directors'] else None
                    if director:
                        # Check if this director is already in preferences
                        existing_directors = [p['preference_value'] for p in current_preferences 
                                            if p['preference_type'] == 'director']
                        if director not in existing_directors:
                            self.db.add_user_preference(user_id, 'director', director)

            return success
        except Exception as e:
            logger.error(f"Error processing user feedback: {e}")
            return False

    async def get_similar_movies(self, movie_title: str, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get similar movies based on a movie title.

        Args:
            movie_title: Title of the movie to find similarities for
            user_id: Optional user ID to exclude already rated movies

        Returns:
            List of similar movies
        """
        try:
            # Get list of already rated movies to exclude them
            excluded_movies = []
            if user_id:
                user_ratings = self.db.get_user_ratings(user_id)
                excluded_movies = [rating['title'] for rating in user_ratings]

            # First, try to get the movie from our database
            movie = self.db.get_movie_by_title(movie_title)

            # If not in database, search TMDB
            if not movie:
                movie_details = await self._get_movie_details_from_tmdb(movie_title)
                if movie_details:
                    movie = movie_details
                    self.db.add_movie(movie_details)

            if not movie:
                logger.warning(f"Could not find movie: {movie_title}")
                return []

            # Get similar movies from TMDB
            tmdb_id = movie.get('tmdb_id')
            if not tmdb_id:
                return []

            similar_url = f"{self.tmdb_base_url}/movie/{tmdb_id}/similar"
            params = {
                "api_key": self.tmdb_api_key,
                "language": "ru-RU"
            }

            # Use httpx instead of requests for better SSL handling
            async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
                # Try up to 3 times with increasing timeout
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = await client.get(similar_url, params=params)
                        response.raise_for_status()
                        similar_results = response.json()
                        break
                    except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout, 
                            httpx.ReadTimeout, ssl.SSLError) as e:
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # Exponential backoff
                            logger.warning(f"TMDB similar movies attempt {attempt+1} failed: {e}. Retrying in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(f"All TMDB similar movies attempts failed: {e}")
                            return []
                else:
                    # All attempts failed
                    return []

                similar_movies = []
                for similar in similar_results.get('results', [])[:10]:  # Get more candidates to filter from
                    movie_title_candidate = self._normalize_text(similar['title'])
                    
                    # Skip movies that user has already rated
                    is_excluded = False
                    for excluded in excluded_movies:
                        if (excluded.lower() in movie_title_candidate.lower() or 
                            movie_title_candidate.lower() in excluded.lower()):
                            is_excluded = True
                            break
                    
                    if is_excluded:
                        logger.info(f"Skipping already rated similar movie: {movie_title_candidate}")
                        continue
                    
                    movie_details = await self._get_movie_details_from_tmdb(movie_title_candidate)
                    if movie_details:
                        # Double-check against excluded list with original and TMDB titles
                        movie_title = movie_details.get('title', '')
                        original_title = movie_details.get('original_title', '')
                        
                        is_excluded = False
                        for excluded in excluded_movies:
                            if (excluded.lower() in movie_title.lower() or 
                                movie_title.lower() in excluded.lower() or
                                (original_title and (excluded.lower() in original_title.lower() or 
                                                    original_title.lower() in excluded.lower()))):
                                is_excluded = True
                                break
                        
                        if not is_excluded:
                            similar_movies.append(movie_details)
                            self.db.add_movie(movie_details)
                            
                            # Stop when we have enough recommendations
                            if len(similar_movies) >= 5:
                                break
                        else:
                            logger.info(f"Skipping excluded similar movie variant: {movie_title}")

                return similar_movies

        except Exception as e:
            logger.error(f"Error getting similar movies: {e}")
            return []

    async def _validate_movie_match(self, movie_data: Dict[str, Any], user_query: str, recommended_title: str) -> bool:
        """
        Validate if the found movie actually matches the user's request.
        
        Args:
            movie_data: Movie details from TMDB
            user_query: Original user query
            recommended_title: Title that AI recommended
            
        Returns:
            True if movie matches the request, False otherwise
        """
        try:
            # Базовые проверки
            if not movie_data:
                return False
            
            # Получаем данные о фильме
            title = movie_data.get('title', '')
            original_title = movie_data.get('original_title', '')
            overview = movie_data.get('overview', '')
            genres = movie_data.get('genres', [])
            release_date = movie_data.get('release_date', '')
            year = release_date[:4] if release_date else ''
            actors = movie_data.get('actors', [])
            directors = movie_data.get('directors', [])
            
            # НОВАЯ ПРОВЕРКА: Специальная валидация для запросов с актерами
            actor_patterns = [
                r'с\s+([А-ЯЁ][а-яё]+[ыоауеймх]?\s+[А-ЯЁ][а-яё]+[ыоауеймх]?)',
                r'актер[а-я]*\s+([А-ЯЁ][а-яё]+[ауы]?\s+[А-ЯЁ][а-яё]+[ауы]?)',
                r'участие[мн]\s+([А-ЯЁ][а-яё]+[ауы]?\s+[А-ЯЁ][а-яё]+[ауы]?)',
            ]
            
            requested_actors = set()
            for pattern in actor_patterns:
                matches = re.findall(pattern, user_query)
                for match in matches:
                    normalized_name = self._normalize_person_name(match.strip())
                    requested_actors.add(normalized_name.lower())
            
            # Если в запросе указан конкретный актер, проверяем его участие
            if requested_actors:
                movie_actors_lower = [actor.lower() for actor in actors]
                
                for requested_actor in requested_actors:
                    found_actor = False
                    for movie_actor in movie_actors_lower:
                        # Проверяем полное совпадение или частичное (имя и фамилия)
                        if (requested_actor in movie_actor or 
                            movie_actor in requested_actor or
                            self._names_match(requested_actor, movie_actor)):
                            found_actor = True
                            break
                    
                    if not found_actor:
                        logger.warning(f"Requested actor '{requested_actor}' not found in '{title}' cast: {actors}")
                        return False
            
            # НОВАЯ ПРОВЕРКА: Специальная валидация для запросов с режиссерами  
            director_patterns = [
                r'от\s+(?:режиссера\s+)?([А-ЯЁ][а-яё]+[ауы]?\s+[А-ЯЁ][а-яё]+[ауы]?)',
                r'режиссер[а-я]*\s+([А-ЯЁ][а-яё]+[ауы]?\s+[А-ЯЁ][а-яё]+[ауы]?)',
            ]
            
            requested_directors = set()
            for pattern in director_patterns:
                matches = re.findall(pattern, user_query)
                for match in matches:
                    normalized_name = self._normalize_person_name(match.strip())
                    requested_directors.add(normalized_name.lower())
            
            # Если в запросе указан конкретный режиссер, проверяем его участие
            if requested_directors:
                movie_directors_lower = [director.lower() for director in directors]
                
                for requested_director in requested_directors:
                    found_director = False
                    for movie_director in movie_directors_lower:
                        if (requested_director in movie_director or 
                            movie_director in requested_director or
                            self._names_match(requested_director, movie_director)):
                            found_director = True
                            break
                    
                    if not found_director:
                        logger.warning(f"Requested director '{requested_director}' not found in '{title}' crew: {directors}")
                        return False
            
            # Создаем описание фильма для проверки
            movie_description = f"""
Название: {title}
Оригинальное название: {original_title}
Год: {year}
Жанры: {', '.join(genres)}
Актеры: {', '.join(actors[:5])}
Режиссеры: {', '.join(directors)}
Описание: {overview}
"""
            
            # Используем ИИ для проверки соответствия (только если не было строгих проверок выше)
            if not requested_actors and not requested_directors:
                validation_prompt = f"""Проанализируй, соответствует ли найденный фильм пользовательскому запросу.

ПОЛЬЗОВАТЕЛЬСКИЙ ЗАПРОС: {user_query}

РЕКОМЕНДОВАННЫЙ БОТОМ ФИЛЬМ: {recommended_title}

НАЙДЕННЫЙ В БАЗЕ ФИЛЬМ:
{movie_description}

Вопросы для анализа:
1. Соответствуют ли жанры найденного фильма запросу пользователя?
2. Подходит ли описание фильма под запрос?
3. Это тот же фильм, который рекомендовал бот, или совершенно другой?

Ответь ТОЛЬКО одним словом:
- "ДА" - если фильм соответствует запросу
- "НЕТ" - если фильм НЕ соответствует запросу

Ответ:"""

                # Настройки для быстрой валидации
                generation_config = {
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "top_k": 20,
                    "max_output_tokens": 10,  # Очень мало токенов - нужен только ДА/НЕТ
                }

                try:
                    response = self.model.generate_content(
                        validation_prompt,
                        generation_config=generation_config
                    )
                    validation_result = response.text.strip().upper()
                    
                    # Проверяем ответ
                    is_valid = "ДА" in validation_result or "YES" in validation_result
                    
                    logger.info(f"AI validation for '{title}': {validation_result} -> {'VALID' if is_valid else 'INVALID'}")
                    return is_valid
                    
                except Exception as e:
                    logger.warning(f"AI validation failed, using fallback validation: {e}")
                    # Fallback валидация без ИИ
                    return self._fallback_validation(movie_data, user_query)
            
            # Если прошли все строгие проверки
            return True
                
        except Exception as e:
            logger.error(f"Error during movie validation: {e}")
            return True  # В случае ошибки разрешаем фильм

    def _names_match(self, name1: str, name2: str) -> bool:
        """
        Check if two names refer to the same person.
        
        Args:
            name1: First name (normalized)
            name2: Second name (from movie data)
            
        Returns:
            True if names likely refer to the same person
        """
        try:
            # Разбиваем имена на части
            parts1 = name1.split()
            parts2 = name2.split()
            
            if len(parts1) >= 2 and len(parts2) >= 2:
                # Проверяем совпадение имени и фамилии
                first_match = any(p1 in p2 or p2 in p1 for p1 in parts1[:1] for p2 in parts2[:1])
                last_match = any(p1 in p2 or p2 in p1 for p1 in parts1[-1:] for p2 in parts2[-1:])
                
                return first_match and last_match
            
            return False
        except:
            return False

    def _fallback_validation(self, movie_data: Dict[str, Any], user_query: str) -> bool:
        """
        Fallback validation without AI when AI validation fails.
        """
        try:
            genres = [g.lower() for g in movie_data.get('genres', [])]
            query_lower = user_query.lower()
            overview = movie_data.get('overview', '').lower()
            
            # Проверяем ключевые слова в запросе и соответствие жанров
            genre_keywords = {
                'боевик': ['боевик', 'экшн', 'action'],
                'комедия': ['комедия', 'comedy'],
                'драма': ['драма', 'drama'],
                'ужасы': ['ужасы', 'хоррор', 'horror'],
                'фантастика': ['фантастика', 'sci-fi', 'научная фантастика'],
                'триллер': ['триллер', 'thriller'],
                'мелодрама': ['мелодрама', 'романтика', 'romance'],
                'детектив': ['детектив', 'mystery'],
                'анимация': ['анимация', 'мультфильм', 'animation'],
                'документальный': ['документальный', 'documentary']
            }
            
            # Определяем ожидаемые жанры на основе запроса
            expected_genres = []
            found_keywords = []
            
            for keyword, genre_list in genre_keywords.items():
                if keyword in query_lower:
                    expected_genres.extend(genre_list)
                    found_keywords.append(keyword)
            
            # Специальные проверки для конкретных запросов
            
            # Проверка для женских ролей
            if any(word in query_lower for word in ['женщин', 'женской', 'героиня', 'девушк']):
                # Если просят фильм с женщиной в главной роли, проверяем описание
                if not any(word in overview for word in ['женщин', 'девушк', 'героиня', 'woman', 'female', 'girl']):
                    logger.info(f"Movie doesn't seem to have female protagonist despite request")
                    
            # Проверка несоответствия жанров (исключения)
            comedy_romance_indicators = ['мелодрама', 'комедия', 'романтический', 'романтика']
            if any(word in query_lower for word in ['боевик', 'экшн', 'action']):
                # Если просят боевик, но нашли мелодраму/комедию
                if any(genre in genres for genre in comedy_romance_indicators):
                    logger.info(f"Requested action but found romance/comedy: {genres}")
                    return False
            
            # Если нашли ожидаемые жанры, проверяем соответствие
            if expected_genres:
                has_matching_genre = any(genre in genres for genre in expected_genres)
                
                # Дополнительная проверка для боевиков
                if 'боевик' in found_keywords:
                    action_genres = ['боевик', 'экшн', 'триллер', 'криминал', 'приключения']
                    has_action = any(genre in genres for genre in action_genres)
                    
                    # Если это явно НЕ боевик (мелодрама, комедия без экшена)
                    non_action_genres = ['мелодрама', 'комедия', 'документальный']
                    is_non_action = any(genre in genres for genre in non_action_genres)
                    
                    if is_non_action and not has_action:
                        logger.info(f"Requested action but found non-action genres: {genres}")
                        return False
                
                logger.info(f"Fallback validation: Expected {expected_genres}, Found {genres}, Match: {has_matching_genre}")
                return has_matching_genre
            
            # Если не смогли определить жанр из запроса, делаем базовую проверку
            # Проверяем, что это не явно неподходящий фильм
            non_matching_patterns = [
                ('боевик', ['мелодрама', 'комедия', 'документальный']),
                ('ужасы', ['комедия', 'мелодрама', 'детский']),
                ('комедия', ['ужасы', 'триллер', 'драма']),
                ('детск', ['ужасы', 'триллер', 'взрослый'])
            ]
            
            for request_pattern, incompatible_genres in non_matching_patterns:
                if request_pattern in query_lower:
                    if any(genre in genres for genre in incompatible_genres):
                        logger.info(f"Incompatible genres found for '{request_pattern}': {genres}")
                        return False
            
            # По умолчанию разрешаем, если не нашли явных противоречий
            return True
            
        except Exception as e:
            logger.error(f"Fallback validation error: {e}")
            return True

    async def _search_person_in_tmdb(self, person_name: str) -> Optional[Dict[str, Any]]:
        """
        Search for a person (actor/director) in TMDB.
        
        Args:
            person_name: Name of the person to search for
            
        Returns:
            Person information from TMDB or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
                search_url = f"{self.tmdb_base_url}/search/person"
                params = {
                    "api_key": self.tmdb_api_key,
                    "query": person_name,
                    "language": "ru-RU"
                }
                
                response = await client.get(search_url, params=params)
                response.raise_for_status()
                search_results = response.json()
                
                if search_results.get('results'):
                    person = search_results['results'][0]  # Берем первый результат
                    
                    # Получаем детальную информацию о человеке
                    person_id = person['id']
                    details_url = f"{self.tmdb_base_url}/person/{person_id}"
                    params = {
                        "api_key": self.tmdb_api_key,
                        "language": "ru-RU",
                        "append_to_response": "movie_credits"
                    }
                    
                    response = await client.get(details_url, params=params)
                    response.raise_for_status()
                    person_details = response.json()
                    
                    return person_details
                    
                return None
                
        except Exception as e:
            logger.error(f"Error searching person in TMDB: {e}")
            return None

    async def _get_movies_by_genre(self, genre_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get popular movies by genre from TMDB.
        
        Args:
            genre_name: Genre name in Russian or English
            limit: Maximum number of movies to return
            
        Returns:
            List of movies in the specified genre
        """
        try:
            # Маппинг жанров на TMDB ID
            genre_mapping = {
                'боевик': 28, 'action': 28,
                'приключения': 12, 'adventure': 12,
                'анимация': 16, 'animation': 16,
                'комедия': 35, 'comedy': 35,
                'криминал': 80, 'crime': 80,
                'документальный': 99, 'documentary': 99,
                'драма': 18, 'drama': 18,
                'семейный': 10751, 'family': 10751,
                'фэнтези': 14, 'fantasy': 14,
                'история': 36, 'history': 36,
                'ужасы': 27, 'horror': 27,
                'музыка': 10402, 'music': 10402,
                'детектив': 9648, 'mystery': 9648,
                'мелодрама': 10749, 'romance': 10749,
                'фантастика': 878, 'science fiction': 878, 'sci-fi': 878,
                'триллер': 53, 'thriller': 53,
                'военный': 10752, 'war': 10752,
                'вестерн': 37, 'western': 37
            }
            
            genre_id = genre_mapping.get(genre_name.lower())
            if not genre_id:
                logger.warning(f"Genre '{genre_name}' not found in mapping")
                return []
            
            async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
                discover_url = f"{self.tmdb_base_url}/discover/movie"
                params = {
                    "api_key": self.tmdb_api_key,
                    "with_genres": genre_id,
                    "language": "ru-RU",
                    "sort_by": "popularity.desc",
                    "page": 1
                }
                
                response = await client.get(discover_url, params=params)
                response.raise_for_status()
                results = response.json()
                
                movies = []
                for movie in results.get('results', [])[:limit]:
                    movie_info = {
                        'title': movie.get('title', ''),
                        'original_title': movie.get('original_title', ''),
                        'release_date': movie.get('release_date', ''),
                        'overview': movie.get('overview', ''),
                        'vote_average': movie.get('vote_average', 0),
                        'tmdb_id': movie.get('id')
                    }
                    movies.append(movie_info)
                
                return movies
                
        except Exception as e:
            logger.error(f"Error getting movies by genre: {e}")
            return []

    async def _get_person_filmography(self, person_name: str, role: str = 'cast') -> List[Dict[str, Any]]:
        """
        Get filmography of a person (actor or director).
        
        Args:
            person_name: Name of the person
            role: 'cast' for actor, 'crew' for director
            
        Returns:
            List of movies the person participated in
        """
        try:
            person_details = await self._search_person_in_tmdb(person_name)
            if not person_details:
                return []
            
            movie_credits = person_details.get('movie_credits', {})
            
            if role == 'cast':
                credits = movie_credits.get('cast', [])
            else:  # crew
                credits = movie_credits.get('crew', [])
                # Фильтруем только режиссеров
                credits = [c for c in credits if c.get('job') == 'Director']
            
            movies = []
            for credit in credits[:15]:  # Ограничиваем до 15 фильмов
                movie_info = {
                    'title': credit.get('title', ''),
                    'original_title': credit.get('original_title', ''),
                    'release_date': credit.get('release_date', ''),
                    'character': credit.get('character', '') if role == 'cast' else '',
                    'job': credit.get('job', '') if role == 'crew' else '',
                    'vote_average': credit.get('vote_average', 0),
                    'tmdb_id': credit.get('id')
                }
                movies.append(movie_info)
            
            # Сортируем по популярности/рейтингу
            movies.sort(key=lambda x: x['vote_average'], reverse=True)
            return movies[:10]  # Возвращаем топ-10
            
        except Exception as e:
            logger.error(f"Error getting person filmography: {e}")
            return []

    async def _enrich_query_with_tmdb_data(self, user_query: str) -> str:
        """
        Enrich user query with real data from TMDB API.
        
        Args:
            user_query: Original user query
            
        Returns:
            Enhanced query with real TMDB data
        """
        try:
            enhanced_query = user_query
            query_lower = user_query.lower()
            
            # Сначала ищем упоминания конкретных фильмов (приоритет выше персон)
            movie_patterns = [
                r'"([^"]+)"',  # фильмы в кавычках
                r'как\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)*)',  # "как Интерстеллар", "как Джон Уик"
                r'типа\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)*)',  # "типа Матрицы", "типа Джон Уик"  
                r'похож[а-я]*\s+на\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)*)',  # "похожие на Джон Уик"
            ]
            
            found_movies = set()
            for pattern in movie_patterns:
                matches = re.findall(pattern, user_query)
                for match in matches:
                    movie_title = match.strip()
                    # Исключаем слишком короткие или служебные слова
                    if len(movie_title) > 2 and movie_title not in ['Все', 'Что', 'Как', 'Где', 'Это', 'Там']:
                        found_movies.add(movie_title)
            
            # Получаем информацию о найденных фильмах
            for movie_title in list(found_movies)[:2]:  # Ограничиваем до 2 фильмов
                logger.info(f"Searching TMDB data for movie: {movie_title}")
                movie_details = await self._get_movie_details_from_tmdb(movie_title)
                if movie_details:
                    genres_str = ", ".join(movie_details.get('genres', []))
                    directors_str = ", ".join(movie_details.get('directors', []))
                    enhanced_query += f"\n\nИнформация из TMDB о фильме \"{movie_details['title']}\": жанры - {genres_str}, режиссер - {directors_str}, рейтинг - {movie_details.get('vote_average', 'N/A')}/10"

            # Ищем упоминания актеров/режиссеров (исключаем уже найденные фильмы)
            person_patterns = [
                r'с\s+([А-ЯЁ][а-яё]+[ыоауеймх]?\s+[А-ЯЁ][а-яё]+[ыоауеймх]?)',  # "с Томом Хэнксом" 
                r'от\s+(?:режиссера\s+)?([А-ЯЁ][а-яё]+[ауы]?\s+[А-ЯЁ][а-яё]+[ауы]?)',  # "от Стивена Спилберга"
                r'актер[а-я]*\s+([А-ЯЁ][а-яё]+[ауы]?\s+[А-ЯЁ][а-яё]+[ауы]?)',  # "актера Роберта Дауни"
                r'режиссер[а-я]*\s+([А-ЯЁ][а-яё]+[ауы]?\s+[А-ЯЁ][а-яё]+[ауы]?)',  # "режиссера Кристофера Нолана"
            ]
            
            found_persons = set()
            for pattern in person_patterns:
                matches = re.findall(pattern, user_query)
                for match in matches:
                    if len(match.split()) == 2:  # Имя и фамилия
                        person_name = match.strip()
                        # Исключаем названия фильмов
                        if person_name not in found_movies:
                            # Преобразуем падежи в именительный падеж (базовая нормализация)
                            normalized_name = self._normalize_person_name(person_name)
                            found_persons.add(normalized_name)
            
            # Получаем информацию о найденных персонах
            for person_name in list(found_persons)[:2]:  # Ограничиваем до 2 персон
                logger.info(f"Searching TMDB data for person: {person_name}")
                
                # Получаем фильмографию как актера
                actor_movies = await self._get_person_filmography(person_name, 'cast')
                if actor_movies:
                    movies_list = ", ".join([f'"{m["title"]}" ({m["release_date"][:4] if m["release_date"] else "N/A"})' 
                                           for m in actor_movies[:5]])
                    enhanced_query += f"\n\nИнформация из TMDB - {person_name} как актер снимался в: {movies_list}"
                
                # Получаем фильмографию как режиссера
                director_movies = await self._get_person_filmography(person_name, 'crew')
                if director_movies:
                    movies_list = ", ".join([f'"{m["title"]}" ({m["release_date"][:4] if m["release_date"] else "N/A"})' 
                                           for m in director_movies[:5]])
                    enhanced_query += f"\n\nИнформация из TMDB - {person_name} как режиссер снял: {movies_list}"
            
            # Ищем упоминания жанров и получаем популярные фильмы
            genre_keywords = {
                'боевик': ['боевик', 'боевики', 'экшн', 'action'],
                'комедия': ['комедия', 'комедии', 'comedy'],
                'драма': ['драма', 'драмы', 'drama'],
                'ужасы': ['ужасы', 'ужас', 'хоррор', 'horror'],
                'фантастика': ['фантастика', 'фантастику', 'sci-fi', 'научная фантастика'],
                'триллер': ['триллер', 'триллеры', 'thriller'],
                'мелодрама': ['мелодрама', 'мелодрамы', 'романтика', 'романтику', 'romance'],
                'детектив': ['детектив', 'детективы', 'mystery'],
                'анимация': ['анимация', 'анимационный', 'мультфильм', 'мультфильмы', 'animation'],
                'документальный': ['документальный', 'документальные', 'documentary']
            }
            
            found_genres = []
            for genre, keywords in genre_keywords.items():
                if any(keyword in query_lower for keyword in keywords):
                    found_genres.append(genre)
            
            # Получаем популярные фильмы для найденных жанров
            for genre in found_genres[:2]:  # Ограничиваем до 2 жанров
                logger.info(f"Getting popular movies for genre: {genre}")
                popular_movies = await self._get_movies_by_genre(genre, 5)
                if popular_movies:
                    movies_list = ", ".join([f'"{m["title"]}" ({m["release_date"][:4] if m["release_date"] else "N/A"}, рейтинг {m["vote_average"]}/10)' 
                                           for m in popular_movies])
                    enhanced_query += f"\n\nПопулярные {genre}ы из TMDB: {movies_list}"
            
            if enhanced_query != user_query:
                logger.info("Query enhanced with TMDB data")
                return enhanced_query
            else:
                logger.info("No additional TMDB data found for query")
                return user_query
                
        except Exception as e:
            logger.error(f"Error enriching query with TMDB data: {e}")
            return user_query

    def _normalize_person_name(self, name: str) -> str:
        """
        Normalize person name from different Russian cases to nominative case.
        
        Args:
            name: Person name in any case
            
        Returns:
            Normalized name in nominative case
        """
        try:
            # Базовая нормализация русских имен и фамилий
            name_mapping = {
                # Популярные актеры (из косвенных падежей в именительный)
                'томом хэнксом': 'Том Хэнкс',
                'тома хэнкса': 'Том Хэнкс',
                'стивена спилберга': 'Стивен Спилберг',
                'стивеном спилбергом': 'Стивен Спилберг',
                'роберта дауни': 'Роберт Дауни',
                'робертом дауни': 'Роберт Дауни',
                'кристофера нолана': 'Кристофер Нолан',
                'кристофером ноланом': 'Кристофер Нолан',
                'леонардо дикаприо': 'Леонардо ДиКаприо',
                'леонардом дикаприо': 'Леонардо ДиКаприо',
                'брэда питта': 'Брэд Питт',
                'брэдом питтом': 'Брэд Питт',
                'джонни деппа': 'Джонни Депп',
                'джонни деппом': 'Джонни Депп',
                'уилла смита': 'Уилл Смит',
                'уиллом смитом': 'Уилл Смит',
                'квентина тарантино': 'Квентин Тарантино',
                'квентином тарантино': 'Квентин Тарантино',
                'мартина скорсезе': 'Мартин Скорсезе',
                'мартином скорсезе': 'Мартин Скорсезе',
                'скарлетт йоханссон': 'Скарлетт Йоханссон',
                'скарлетт йоханссон': 'Скарлетт Йоханссон',
                'анджелины джоли': 'Анджелина Джоли',
                'анджелиной джоли': 'Анджелина Джоли',
            }
            
            name_lower = name.lower().strip()
            
            # Проверяем прямое соответствие
            if name_lower in name_mapping:
                return name_mapping[name_lower]
            
            # Базовая обработка окончаний для неизвестных имен
            words = name.split()
            if len(words) == 2:
                first_name, last_name = words
                
                # Убираем типичные окончания косвенных падежей
                # Имена
                if first_name.lower().endswith(('ом', 'ем', 'ым', 'ым')):
                    first_name = first_name[:-2]
                elif first_name.lower().endswith(('а', 'я', 'у', 'ю', 'ы', 'и', 'е')):
                    if len(first_name) > 3:  # Избегаем слишком коротких имен
                        first_name = first_name[:-1]
                
                # Фамилии
                if last_name.lower().endswith(('ом', 'ем', 'ым', 'им')):
                    last_name = last_name[:-2]
                elif last_name.lower().endswith(('а', 'я', 'у', 'ю', 'ы', 'и', 'е')):
                    if len(last_name) > 4:  # Фамилии обычно длиннее
                        last_name = last_name[:-1]
                
                return f"{first_name.title()} {last_name.title()}"
            
            return name.title()
            
        except Exception as e:
            logger.error(f"Error normalizing person name: {e}")
            return name.title() 