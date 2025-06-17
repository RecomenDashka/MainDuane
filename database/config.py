import os
import sqlite3
from typing import Optional # Добавлено для более точной типизации

# Определяем путь к базе данных.
# os.path.dirname(__file__) получает директорию текущего файла.
# '..' поднимается на один уровень вверх.
# 'data' указывает на поддиректорию 'data'.
# 'movie_recommendations.db' - имя файла базы данных.
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'movie_recommendations.db')

def get_db_connection() -> Optional[sqlite3.Connection]:
    """
    Устанавливает соединение с базой данных SQLite.

    Настраивает соединение так, чтобы строки результатов можно было
    получать как объекты sqlite3.Row (доступ по имени столбца)
    и чтобы оно было безопасно для использования в многопоточных/асинхронных средах
    (check_same_thread=False).

    Returns:
        Объект sqlite3.Connection, если соединение установлено успешно,
        иначе None.
    """
    conn: Optional[sqlite3.Connection] = None
    try:
        # check_same_thread=False позволяет использовать соединение из разных потоков
        # или асинхронных задач без ошибок, связанных с доступом к соединению из разных потоков.
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row # Позволяет обращаться к столбцам по имени (e.g., row['column_name'])
        return conn
    except sqlite3.Error as e:
        # Логируем ошибку, если произошла проблема с подключением к базе данных
        print(f"Ошибка подключения к базе данных по пути {DB_PATH}: {e}")
        return None
    except Exception as e:
        # Логируем любые другие непредвиденные ошибки
        print(f"Непредвиденная ошибка при получении соединения с базой данных: {e}")
        return None

# Пример использования (для демонстрации, в реальном приложении обычно управляется из других модулей)
# if __name__ == "__main__":
#     conn = get_db_connection()
#     if conn:
#         print(f"Соединение с базой данных {DB_PATH} успешно установлено.")
#         # Здесь можно выполнять операции с базой данных
#         conn.close()
#         print("Соединение закрыто.")
#     else:
#         print("Не удалось установить соединение с базой данных.")