import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Tuple  # Добавлено для более точной типизации
from core.logger import get_logger

logger = get_logger("feedback_agent")


class FeedbackAgent:
    """
    Агент для управления обратной связью пользователей, сохраняемой в SQLite базе данных.
    """

    def __init__(self, db_path: str = "data/movie_feedback.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """
        Инициализирует базу данных и создает таблицу 'feedback', если она не существует.
        Использует `check_same_thread=False` для совместимости с асинхронными средами.
        """
        try:
            # check_same_thread=False позволяет использовать соединение из разных потоков
            # (актуально для асинхронных фреймворков, которые могут переключать контекст)
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                               CREATE TABLE IF NOT EXISTS feedback
                               (
                                   id
                                   INTEGER
                                   PRIMARY
                                   KEY
                                   AUTOINCREMENT,
                                   user_id
                                   TEXT
                                   NOT
                                   NULL,
                                   query
                                   TEXT,
                                   feedback
                                   TEXT
                                   NOT
                                   NULL,
                                   timestamp
                                   TEXT
                                   NOT
                                   NULL
                               )
                               """)
                conn.commit()
            logger.info(f"Таблица 'feedback' успешно инициализирована в {self.db_path}.")
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при инициализации таблицы feedback: {e}")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при инициализации таблицы feedback: {e}")

    def save_feedback(self, user_id: str, query: str, feedback: str) -> None:
        """
        Сохраняет обратную связь пользователя в базу данных.

        Args:
            user_id: Идентификатор пользователя (например, user_id из Telegram).
            query: Запрос пользователя, на который была дана обратная связь.
            feedback: Текст обратной связи от пользователя.
        """
        timestamp = datetime.utcnow().isoformat()  # ISO формат для удобства хранения и сортировки
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                               INSERT INTO feedback (user_id, query, feedback, timestamp)
                               VALUES (?, ?, ?, ?)
                               """, (user_id, query, feedback, timestamp))
                conn.commit()
            logger.info(f"Сохранена обратная связь от пользователя '{user_id}' для запроса '{query[:50]}...'.")
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при сохранении обратной связи от пользователя {user_id}: {e}")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при сохранении обратной связи от пользователя {user_id}: {e}")

    def get_feedback_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Извлекает всю обратную связь, оставленную конкретным пользователем.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Список словарей, каждый из которых представляет запись обратной связи
            с полями 'query', 'feedback', 'timestamp'. Возвращает пустой список в случае ошибки.
        """
        feedback_list: List[Dict[str, Any]] = []
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row  # Позволяет обращаться к столбцам по имени
                cursor = conn.cursor()
                cursor.execute("""
                               SELECT query, feedback, timestamp
                               FROM feedback
                               WHERE user_id = ?
                               ORDER BY timestamp DESC
                               """, (user_id,))
                rows = cursor.fetchall()
                feedback_list = [dict(row) for row in rows]  # Преобразуем Row объекты в словари
            logger.info(f"Получено {len(feedback_list)} записей обратной связи для пользователя {user_id}.")
            return feedback_list
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при получении обратной связи для пользователя {user_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при получении обратной связи для пользователя {user_id}: {e}")
            return []

    def get_all_feedback(self) -> List[Dict[str, Any]]:
        """
        Извлекает всю обратную связь из базы данных.

        Returns:
            Список словарей, каждый из которых представляет запись обратной связи.
            Возвращает пустой список в случае ошибки.
        """
        all_feedback: List[Dict[str, Any]] = []
        try:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                               SELECT id, user_id, query, feedback, timestamp
                               FROM feedback
                               ORDER BY timestamp DESC
                               """)
                rows = cursor.fetchall()
                all_feedback = [dict(row) for row in rows]
            logger.info(f"Получено {len(all_feedback)} всего записей обратной связи.")
            return all_feedback
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при получении всей обратной связи: {e}")
            return []
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при получении всей обратной связи: {e}")
            return []