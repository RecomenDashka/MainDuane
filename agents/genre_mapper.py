# agents/genre_mapper.py

import sqlite3
import re
from typing import List, Optional, Set
from core.logger import get_logger

logger = get_logger(__name__)


class GenreMapper:
    def __init__(self,
                 db_path: str = "movie_recommendations.db"):  # Убрал "data/" если база в корне или другом известном месте
        self.db_path = db_path
        self.genres: List[str] = []  # Инициализация как список строк
        self._load_genres()  # Загружаем жанры при инициализации

    def _load_genres(self) -> None:
        """
        Загружает уникальные жанры из столбца 'genres' таблицы 'movies' в базе данных.
        Предполагается, что жанры хранятся как строки, разделенные запятыми (e.g., "Action, Thriller").
        """
        unique_genres: Set[str] = set()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # Позволяет обращаться к столбцам по имени
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT genres FROM movies WHERE genres IS NOT NULL AND genres != ''")

                for row in cursor.fetchall():
                    genre_string = row["genres"]
                    if genre_string:
                        # Разделяем строку на отдельные жанры, убираем пробелы и приводим к нижнему регистру
                        individual_genres = [g.strip().lower() for g in genre_string.split(',') if g.strip()]
                        unique_genres.update(individual_genres)

            self.genres = sorted(list(unique_genres))  # Сортируем для консистентности
            logger.info(f"Loaded {len(self.genres)} unique genres from database.")
        except sqlite3.Error as e:
            logger.error(f"SQLite error loading genres from database: {e}")
            self.genres = []  # В случае ошибки сбрасываем жанры
        except Exception as e:
            logger.error(f"Error loading genres from database: {e}")
            self.genres = []  # В случае ошибки сбрасываем жанры

    def get_all_genres(self) -> List[str]:
        """
        Возвращает список всех загруженных уникальных жанров.

        Returns:
            Список строк, представляющих жанры.
        """
        return self.genres

    def match_genres(self, user_input: str) -> List[str]:
        """
        Находит жанры, присутствующие в пользовательском вводе, используя более точное сопоставление
        (с учетом границ слов).

        Args:
            user_input: Строка текста от пользователя, которая может содержать названия жанров.

        Returns:
            Список строк, представляющих найденные жанры.
        """
        matched: List[str] = []
        user_input_lower = user_input.lower()

        for genre in self.genres:
            # Используем регулярное выражение с \b (границей слова) для более точного совпадения.
            # Например, 'action' не будет совпадать с 'transaction'.
            # re.escape(genre) нужен, чтобы экранировать спецсимволы в названии жанра, если они есть.
            pattern = r'\b' + re.escape(genre) + r'\b'
            if re.search(pattern, user_input_lower):
                matched.append(genre)

        # Удаляем дубликаты и сохраняем порядок, если нужно (здесь просто set для уникальности)
        # Если порядок важен, можно использовать collections.OrderedDict.fromkeys(matched)
        return list(set(matched))