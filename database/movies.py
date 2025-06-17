import sqlite3
import json
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from core.logger import get_logger

logger = get_logger("movie_database")


class MovieDatabase:
    """
    Управляет базой данных SQLite для хранения информации о пользователях, фильмах,
    предпочтениях, рейтингах и истории взаимодействий.
    """

    def __init__(self, db_path: str):
        """
        Инициализирует MovieDatabase и устанавливает соединение с базой данных.
        """
        try:
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._ensure_tables()
            logger.info(f"Соединение с базой данных {db_path} успешно установлено и таблицы проверены.")
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при подключении к базе данных или инициализации таблиц по пути {db_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при инициализации MovieDatabase: {e}")
            raise

    def _ensure_tables(self) -> None:
        """
        Создает необходимые таблицы в базе данных, если они не существуют.
        """
        cursor = self.conn.cursor()

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS users
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           user_id
                           INTEGER
                           UNIQUE
                           NOT
                           NULL,
                           username
                           TEXT,
                           joined_at
                           DATETIME
                           DEFAULT
                           CURRENT_TIMESTAMP
                       )
                       """)

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS movies
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           tmdb_id
                           INTEGER
                           UNIQUE
                           NOT
                           NULL,
                           title
                           TEXT
                           NOT
                           NULL,
                           original_title
                           TEXT,
                           overview
                           TEXT,
                           release_date
                           TEXT,
                           vote_average
                           REAL,
                           poster_path
                           TEXT,
                           backdrop_path
                           TEXT,
                           genres
                           TEXT,
                           runtime
                           INTEGER,
                           actors
                           TEXT,
                           directors
                           TEXT,
                           popularity
                           REAL,
                           added_at
                           DATETIME
                           DEFAULT
                           CURRENT_TIMESTAMP
                       )
                       """)

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS user_preferences
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           user_id
                           INTEGER
                           NOT
                           NULL,
                           preference_type
                           TEXT
                           NOT
                           NULL,
                           preference_value
                           TEXT
                           NOT
                           NULL,
                           created_at
                           DATETIME
                           DEFAULT
                           CURRENT_TIMESTAMP,
                           UNIQUE
                       (
                           user_id,
                           preference_type,
                           preference_value
                       ),
                           FOREIGN KEY
                       (
                           user_id
                       ) REFERENCES users
                       (
                           user_id
                       ) ON DELETE CASCADE
                           )
                       """)

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS ratings
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           user_id
                           INTEGER
                           NOT
                           NULL,
                           movie_id
                           INTEGER
                           NOT
                           NULL,
                           rating
                           INTEGER
                           NOT
                           NULL,
                           rated_at
                           DATETIME
                           DEFAULT
                           CURRENT_TIMESTAMP,
                           UNIQUE
                       (
                           user_id,
                           movie_id
                       ),
                           FOREIGN KEY
                       (
                           user_id
                       ) REFERENCES users
                       (
                           user_id
                       ) ON DELETE CASCADE,
                           FOREIGN KEY
                       (
                           movie_id
                       ) REFERENCES movies
                       (
                           id
                       )
                         ON DELETE CASCADE
                           )
                       """)

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS history
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           user_id
                           INTEGER
                           NOT
                           NULL,
                           movie_id
                           INTEGER
                           NOT
                           NULL,
                           action_type
                           TEXT
                           NOT
                           NULL,
                           timestamp
                           DATETIME
                           DEFAULT
                           CURRENT_TIMESTAMP,
                           FOREIGN
                           KEY
                       (
                           user_id
                       ) REFERENCES users
                       (
                           user_id
                       ) ON DELETE CASCADE,
                           FOREIGN KEY
                       (
                           movie_id
                       ) REFERENCES movies
                       (
                           id
                       )
                         ON DELETE CASCADE
                           )
                       """)

        self.conn.commit()
        logger.info("Все необходимые таблицы базы данных проверены/созданы.")

    def add_user(self, user_id: int, username: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
            self.conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Пользователь {username} (ID: {user_id}) добавлен в базу данных.")
                return True
            else:
                logger.info(f"Пользователь {username} (ID: {user_id}) уже существует в базе данных.")
                return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при добавлении пользователя {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при добавлении пользователя: {e}")
            return False

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        return dict(user_data) if user_data else None

    def add_movie(self, movie_data: Dict[str, Any]) -> Optional[int]:
        try:
            actors_json = json.dumps([a['name'] for a in movie_data.get('actors', [])])
            directors_json = json.dumps([d['name'] for d in movie_data.get('directors', [])])
            genres_str = ", ".join(movie_data.get('genres', []))

            cursor = self.conn.cursor()
            cursor.execute("""
                           INSERT INTO movies (tmdb_id, title, original_title, overview, release_date, vote_average,
                                               poster_path, backdrop_path, genres, runtime, actors, directors,
                                               popularity)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(tmdb_id) DO
                           UPDATE SET
                               title = EXCLUDED.title,
                               original_title = EXCLUDED.original_title,
                               overview = EXCLUDED.overview,
                               release_date = EXCLUDED.release_date,
                               vote_average = EXCLUDED.vote_average,
                               poster_path = EXCLUDED.poster_path,
                               backdrop_path = EXCLUDED.backdrop_path,
                               genres = EXCLUDED.genres,
                               runtime = EXCLUDED.runtime,
                               actors = EXCLUDED.actors,
                               directors = EXCLUDED.directors,
                               popularity = EXCLUDED.popularity
                           """, (
                               movie_data.get('tmdb_id'),
                               movie_data.get('title'),
                               movie_data.get('original_title'),
                               movie_data.get('overview'),
                               movie_data.get('release_date'),
                               movie_data.get('vote_average'),
                               movie_data.get('poster_path'),
                               movie_data.get('backdrop_path'),
                               genres_str,
                               movie_data.get('runtime'),
                               actors_json,
                               directors_json,
                               movie_data.get('popularity')
                           ))
            self.conn.commit()

            movie_id = cursor.lastrowid
            logger.info(
                f"Фильм '{movie_data.get('title')}' (TMDB ID: {movie_data.get('tmdb_id')}) добавлен/обновлен в базу данных.")
            return movie_id
        except sqlite3.Error as e:
            logger.error(
                f"Ошибка SQLite при добавлении/обновлении фильма {movie_data.get('title')} (TMDB ID: {movie_data.get('tmdb_id')}): {e}")
            return None
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при добавлении/обновлении фильма: {e}")
            return None

    def get_movie(self, movie_db_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM movies WHERE id = ?", (movie_db_id,))
        movie_data = cursor.fetchone()
        if movie_data:
            movie_dict = dict(movie_data)
            try:
                if movie_dict.get('actors'):
                    movie_dict['actors'] = [{'name': name} for name in json.loads(movie_dict['actors'])]
                if movie_dict.get('directors'):
                    movie_dict['directors'] = [{'name': name} for name in json.loads(movie_dict['directors'])]
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Ошибка декодирования JSON для актеров/режиссеров фильма {movie_db_id}: {e}")
                movie_dict['actors'] = []
                movie_dict['directors'] = []
            if movie_dict.get('genres') and isinstance(movie_dict['genres'], str):
                movie_dict['genres'] = [g.strip() for g in movie_dict['genres'].split(',')]
            return movie_dict
        return None

    def get_movie_by_tmdb_id(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM movies WHERE tmdb_id = ?", (tmdb_id,))
        movie_data = cursor.fetchone()
        if movie_data:
            movie_dict = dict(movie_data)
            try:
                if movie_dict.get('actors'):
                    movie_dict['actors'] = [{'name': name} for name in json.loads(movie_dict['actors'])]
                if movie_dict.get('directors'):
                    movie_dict['directors'] = [{'name': name} for name in json.loads(movie_dict['directors'])]
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Ошибка декодирования JSON для актеров/режиссеров фильма с TMDB ID {tmdb_id}: {e}")
                movie_dict['actors'] = []
                movie_dict['directors'] = []
            if movie_dict.get('genres') and isinstance(movie_dict['genres'], str):
                movie_dict['genres'] = [g.strip() for g in movie_dict['genres'].split(',')]
            return movie_dict
        return None

    def get_movie_id_by_tmdb_id(self, tmdb_id: int) -> Optional[int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM movies WHERE tmdb_id = ?", (tmdb_id,))
        result = cursor.fetchone()
        return result['id'] if result else None

    def add_user_preference(self, user_id: int, preference_type: str, preference_value: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO user_preferences (user_id, preference_type, preference_value)
                VALUES (?, ?, ?)
            """, (user_id, preference_type.lower(), preference_value.lower()))
            self.conn.commit()
            logger.info(
                f"Предпочтение '{preference_type}: {preference_value}' добавлено/обновлено для пользователя {user_id}.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при добавлении предпочтения для пользователя {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при добавлении предпочтения: {e}")
            return False

    def get_user_preferences(self, user_id: int) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT preference_type, preference_value FROM user_preferences WHERE user_id = ?", (user_id,))
        return [dict(row) for row in cursor.fetchall()]

    def clear_user_preferences(self, user_id: int) -> bool:
        try:
            self.conn.execute("DELETE FROM user_preferences WHERE user_id = ?", (user_id,))
            self.conn.commit()
            logger.info(f"Предпочтения пользователя {user_id} успешно очищены.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при очистке предпочтений для user_id={user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при очистке предпочтений: {e}")
            return False

    def add_rating(self, user_id: int, movie_id: int, rating: int) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                           INSERT INTO ratings (user_id, movie_id, rating)
                           VALUES (?, ?, ?) ON CONFLICT(user_id, movie_id) DO
                           UPDATE SET
                               rating = EXCLUDED.rating,
                               rated_at = CURRENT_TIMESTAMP
                           """, (user_id, movie_id, rating))
            self.conn.commit()
            logger.info(f"Оценка {rating} для фильма {movie_id} от пользователя {user_id} добавлена/обновлена.")
            return True
        except sqlite3.Error as e:
            logger.error(
                f"Ошибка SQLite при добавлении/обновлении оценки для user_id={user_id}, movie_id={movie_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при добавлении/обновлении оценки: {e}")
            return False

    def get_user_ratings(self, user_id: int) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("""
                       SELECT r.rating, m.title, m.tmdb_id, r.movie_id, r.rated_at
                       FROM ratings r
                                JOIN movies m ON r.movie_id = m.id
                       WHERE r.user_id = ?
                       ORDER BY r.rated_at DESC
                       """, (user_id,))
        return [dict(row) for row in cursor.fetchall()]

    def add_user_history(self, user_id: int, movie_id: int, action_type: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO history (user_id, movie_id, action_type) VALUES (?, ?, ?)",
                (user_id, movie_id, action_type)
            )
            self.conn.commit()
            logger.info(
                f"Запись истории добавлена: user_id={user_id}, movie_id={movie_id}, action_type='{action_type}'.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при добавлении истории для user_id={user_id}, movie_id={movie_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при добавлении истории: {e}")
            return False

    def get_user_history(self, user_id: int, limit: int = 20, action_type: Optional[str] = None) -> List[
        Dict[str, Any]]:
        """
        Получает историю взаимодействий пользователя с фильмами.
        Добавлен опциональный фильтр по action_type.
        """
        cursor = self.conn.cursor()
        query = """
                SELECT h.movie_id, h.action_type, h.timestamp, m.title
                FROM history h
                         JOIN movies m ON h.movie_id = m.id
                WHERE h.user_id = ? \
                """
        params = [user_id]

        if action_type:
            query += " AND h.action_type = ?"
            params.append(action_type)

        query += " ORDER BY h.timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]

    def clear_user_history(self, user_id: int) -> bool:
        try:
            self.conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
            self.conn.commit()
            logger.info(f"История пользователя {user_id} успешно очищена.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при очистке истории для user_id={user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при очистке истории: {e}")
            return False

    def update_movie(self, movie_id: int, updated_data: Dict[str, Any]) -> bool:
        set_clauses = []
        values = []
        for key, value in updated_data.items():
            if key in ['title', 'original_title', 'overview', 'release_date', 'poster_path', 'backdrop_path']:
                set_clauses.append(f"{key} = ?")
                values.append(value)
            elif key == 'vote_average' or key == 'popularity':
                set_clauses.append(f"{key} = ?")
                values.append(float(value))
            elif key == 'runtime':
                set_clauses.append(f"{key} = ?")
                values.append(int(value))
            elif key == 'genres' and isinstance(value, list):
                set_clauses.append(f"{key} = ?")
                values.append(", ".join(value))
            elif key in ['actors', 'directors'] and isinstance(value, list):
                set_clauses.append(f"{key} = ?")
                values.append(json.dumps([item['name'] for item in value]))

        if not set_clauses:
            logger.warning(f"Нет данных для обновления фильма с ID {movie_id}.")
            return False

        values.append(movie_id)
        update_query = f"UPDATE movies SET {', '.join(set_clauses)} WHERE id = ?"

        try:
            cursor = self.conn.cursor()
            cursor.execute(update_query, tuple(values))
            self.conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Фильм с ID {movie_id} успешно обновлен.")
                return True
            else:
                logger.warning(f"Фильм с ID {movie_id} не найден или не было изменений.")
                return False
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при обновлении фильма с ID {movie_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при обновлении фильма с ID {movie_id}: {e}")
            return False

    def delete_movie(self, movie_id: int) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
            self.conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Фильм с ID {movie_id} успешно удален из базы данных.")
                return True
            else:
                logger.warning(f"Фильм с ID {movie_id} не найден для удаления.")
                return False
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при удалении фильма с ID {movie_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при удалении фильма с ID {movie_id}: {e}")
            return False

