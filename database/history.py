from typing import List, Dict, Any, Optional
import sqlite3
from core.logger import get_logger # Импортируем наш настроенный логгер

logger = get_logger("history_manager")

class HistoryManager:
    """
    Управляет историей взаимодействий пользователя с фильмами в базе данных SQLite.
    Предполагается, что база данных содержит таблицу 'history' со столбцами
    'user_id', 'movie_id', 'action_type' и 'timestamp'.
    """
    def __init__(self, conn: sqlite3.Connection):
        """
        Инициализирует HistoryManager.

        Args:
            conn: Открытое и настроенное соединение с базой данных SQLite.
        """
        self.conn = conn
        # Убедимся, что conn настроен на возвращение строк как dict-подобных объектов
        if self.conn.row_factory is None:
            self.conn.row_factory = sqlite3.Row

    def add(self, user_id: int, movie_id: int, action_type: str) -> bool:
        """
        Добавляет новую запись в историю взаимодействия пользователя.

        Args:
            user_id: ID пользователя.
            movie_id: ID фильма.
            action_type: Тип действия (например, 'recommendation', 'view', 'like', 'dislike').

        Returns:
            True, если запись успешно добавлена, иначе False.
        """
        try:
            # timestamp будет установлен автоматически благодаря DEFAULT CURRENT_TIMESTAMP в схеме таблицы
            self.conn.execute(
                """
                INSERT INTO history (user_id, movie_id, action_type)
                VALUES (?, ?, ?)
                """,
                (user_id, movie_id, action_type)
            )
            self.conn.commit()
            logger.info(f"Добавлена запись в историю: user_id={user_id}, movie_id={movie_id}, action_type='{action_type}'")
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при добавлении в историю (user_id={user_id}, movie_id={movie_id}, action_type='{action_type}'): {e}")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при добавлении в историю: {e}")
            return False

    def get(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Получает всю историю взаимодействий для конкретного пользователя.

        Args:
            user_id: ID пользователя.

        Returns:
            Список словарей, каждый из которых представляет запись истории.
            Возвращает пустой список, если история не найдена или произошла ошибка.
        """
        try:
            cur = self.conn.execute(
                "SELECT * FROM history WHERE user_id = ? ORDER BY timestamp DESC",
                (user_id,)
            )
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при получении истории для user_id={user_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при получении истории: {e}")
            return []

    def count(self, user_id: int) -> int:
        """
        Подсчитывает количество записей в истории для конкретного пользователя.

        Args:
            user_id: ID пользователя.

        Returns:
            Количество записей в истории, или 0 в случае ошибки.
        """
        try:
            cur = self.conn.execute(
                "SELECT COUNT(*) as count FROM history WHERE user_id = ?",
                (user_id,)
            )
            result = cur.fetchone()
            return result["count"] if result else 0
        except sqlite3.Error as e:
            logger.error(f"Ошибка SQLite при подсчете истории для user_id={user_id}: {e}")
            return 0
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при подсчете истории: {e}")
            return 0

    def clear(self, user_id: int) -> bool:
        """
        Удаляет все записи истории для конкретного пользователя.

        Args:
            user_id: ID пользователя.

        Returns:
            True, если история успешно очищена, иначе False.
        """
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