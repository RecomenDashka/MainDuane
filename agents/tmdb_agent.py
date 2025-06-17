import os
import httpx
import asyncio
import json  # Добавлен импорт для обработки JSON-строк актеров/режиссеров
from typing import Dict, Any, List, Optional, Tuple
from core.logger import get_logger

logger = get_logger("tmdb_agent")


class TMDBAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/w500"  # Базовый URL для постеров
        # httpx.AsyncClient рекомендуется создавать один раз и переиспользовать
        # но для простоты примера, создаем его внутри методов с async with
        # В реальном приложении лучше инжектировать или создавать один раз при инициализации класса
        # self.client = httpx.AsyncClient(timeout=10.0)

    async def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None,
                            retries: int = 3, delay: int = 1) -> Optional[Dict[str, Any]]:
        """
        Вспомогательный метод для выполнения асинхронных HTTP GET запросов к TMDB API
        с поддержкой повторных попыток и экспоненциальной задержкой.
        По умолчанию добавляет параметр 'language' для русского языка.

        Args:
            endpoint: Конечная точка API (например, "search/movie", "movie/{id}").
            params: Словарь параметров запроса.
            retries: Максимальное количество попыток выполнения запроса.
            delay: Начальная задержка между попытками в секундах (удваивается при каждой неудаче).

        Returns:
            Словарь с данными JSON ответа API или None в случае ошибки.
        """
        full_url = f"{self.base_url}/{endpoint}"

        # Объединяем дефолтные параметры с переданными
        effective_params = {
            "api_key": self.api_key,
            "language": "ru-RU"  # Установка русского языка по умолчанию для всех запросов
        }
        if params:
            effective_params.update(params)

        current_delay = delay
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:  # Создаем клиент внутри, если не инжектируем
                    response = await client.get(full_url, params=effective_params)
                    response.raise_for_status()  # Вызывает исключение для HTTP ошибок (4xx, 5xx)
                    return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"TMDB HTTP error (attempt {attempt + 1}/{retries}): {e.response.status_code} - {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"TMDB Request error (attempt {attempt + 1}/{retries}): {e}")
            except Exception as e:
                logger.error(f"TMDB API call failed with unexpected error (attempt {attempt + 1}/{retries}): {e}")

            if attempt < retries - 1:
                await asyncio.sleep(current_delay)
                current_delay *= 2
            else:
                logger.error(f"Failed to fetch data from TMDB after {retries} attempts for endpoint: {endpoint}")
        return None

    async def search_movie(self, query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Ищет фильмы по запросу.

        Args:
            query: Название фильма для поиска.
            year: Год выпуска фильма (опционально, сейчас не используется в _make_request).

        Returns:
            Список словарей с базовой информацией о найденных фильмах.
        """
        params = {"query": query}
        # Параметр 'year' больше не добавляется в запрос к TMDB, т.к. удален из логики enrich_query
        # if year:
        #     params["year"] = year # Это теперь игнорируется в _make_request, но оставим для сигнатуры, если нужно

        data = await self._make_request("search/movie", params=params)
        movies = []
        if data and data.get("results"):
            for movie in data["results"]:
                movies.append({
                    "tmdb_id": movie.get("id"),
                    "title": movie.get("title"),
                    "original_title": movie.get("original_title"),
                    "release_date": movie.get("release_date"),
                    "poster_path": movie.get("poster_path"),
                    "backdrop_path": movie.get("backdrop_path"),
                    "vote_average": movie.get("vote_average"),
                    "overview": movie.get("overview"),
                    "popularity": movie.get("popularity")
                })
        logger.info(f"Найдено {len(movies)} фильмов для запроса '{query}'.")
        return movies

    async def get_movie_details(self, movie_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает полные детали фильма по ID.

        Args:
            movie_id: ID фильма в TMDB.

        Returns:
            Словарь с полной информацией о фильме.
        """
        # Параметры 'append_to_response' позволяют получить дополнительные данные
        # в одном запросе, например, кредиты (актеры, режиссеры)
        data = await self._make_request(f"movie/{movie_id}", params={"append_to_response": "credits"})

        if data:
            # Извлекаем жанры
            genres = [g.get("name") for g in data.get("genres", []) if g.get("name")]

            # Извлекаем актеров и режиссеров
            actors = []
            directors = []
            credits_data = data.get("credits")
            if credits_data:
                for cast_member in credits_data.get("cast", [])[:5]:  # До 5 актеров
                    actors.append({"name": cast_member.get("name"), "character": cast_member.get("character")})
                for crew_member in credits_data.get("crew", []):
                    if crew_member.get("job") == "Director":
                        directors.append({"name": crew_member.get("name")})

            # Формируем URL постера
            poster_url = f"{self.image_base_url}{data['poster_path']}" if data.get('poster_path') else None

            details = {
                "tmdb_id": data.get("id"),
                "title": data.get("title"),  # Это теперь будет русское название, если доступно
                "original_title": data.get("original_title"),
                "overview": data.get("overview"),  # Это теперь будет русское описание, если доступно
                "release_date": data.get("release_date"),
                "vote_average": data.get("vote_average"),
                "poster_path": data.get("poster_path"),  # Сам путь
                "poster_url": poster_url,  # Полный URL для удобства
                "backdrop_path": data.get("backdrop_path"),
                "runtime": data.get("runtime"),
                "genres": genres,
                "actors": actors,
                "directors": directors,
                "popularity": data.get("popularity")
            }
            logger.info(f"Получены детали для фильма '{details.get('title')}' (TMDB ID: {details.get('tmdb_id')}).")
            return details
        logger.warning(f"Не удалось получить детали для фильма ID: {movie_id}.")
        return None

    async def enrich_query(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Ищет фильм по названию и обогащает его полными деталями.

        Args:
            query: Название фильма для поиска.

        Returns:
            Полный словарь с данными о фильме или None, если фильм не найден.
        """
        search_results = await self.search_movie(query)
        if search_results:
            # Берем первый результат поиска и получаем его полные детали
            first_result_id = search_results[0].get("tmdb_id")
            if first_result_id:
                details = await self.get_movie_details(first_result_id)
                if details:
                    logger.info(f"Фильм '{details.get('title')}' обогащен данными.")
                    return details
        logger.warning(f"Не удалось обогатить данные для запроса: '{query}'.")
        return None

    async def get_credits(self, movie_id: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Получает информацию об актерах и режиссерах фильма по ID.
        Этот метод может быть вызван отдельно, но его логика уже в get_movie_details.
        """
        credits_data = await self._make_request(f"movie/{movie_id}/credits")
        actors = []
        directors = []

        if credits_data:
            # Получаем 5 основных актеров
            for cast_member in credits_data.get("cast", [])[:5]:
                actors.append({"name": cast_member.get("name"), "character": cast_member.get("character")})

            # Получаем режиссеров
            for crew_member in credits_data.get("crew", []):
                if crew_member.get("job") == "Director":
                    directors.append({"name": crew_member.get("name")})
        logger.info(f"Получены кредиты для фильма ID: {movie_id}. Актеры: {len(actors)}, Режиссеры: {len(directors)}.")
        return actors, directors

    async def get_similar_movies(self, movie_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Получает список похожих фильмов по ID фильма.

        Args:
            movie_id: ID фильма в TMDB.
            limit: Максимальное количество похожих фильмов для возврата.

        Returns:
            Список словарей с информацией о похожих фильмах.
        """
        similar_data = await self._make_request(f"movie/{movie_id}/similar")
        similar_movies = []
        if similar_data and similar_data.get("results"):
            for movie in similar_data["results"][:limit]:
                poster_url = f"{self.image_base_url}{movie['poster_path']}" if movie.get('poster_path') else None
                similar_movies.append({
                    "tmdb_id": movie.get("id"),
                    "title": movie.get("title"),
                    "release_date": movie.get("release_date"),
                    "poster_path": movie.get("poster_path"),
                    "poster_url": poster_url
                })
        logger.info(f"Найдено {len(similar_movies)} похожих фильмов для ID: {movie_id}.")
        return similar_movies

