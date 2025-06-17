import logging
from logging.handlers import RotatingFileHandler
import os
from typing import Optional

# Директория для хранения логов
LOG_DIR = "logs"
# Имя файла логов
LOG_FILE = "recomen_dashka.log"
# Максимальный размер файла логов (в байтах): 1MB
MAX_BYTES = 1_000_000
# Количество резервных файлов логов
BACKUP_COUNT = 3

# Создаём директорию для логов, если её нет
os.makedirs(LOG_DIR, exist_ok=True)

# Форматтер для логов
LOG_FORMATTER = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Возвращает настроенный объект логгера. Если логгер с таким именем
    уже был настроен (т.е. у него уже есть хэндлеры), он возвращает существующий.
    Это предотвращает дублирование хэндлеров при многократном вызове.

    Args:
        name: Имя логгера (обычно __name__ файла).
        level: Уровень логирования (например, logging.INFO, logging.DEBUG).

    Returns:
        Настроенный объект logging.Logger.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Проверяем, были ли уже добавлены хэндлеры к этому логгеру
    # Это важно для предотвращения многократного добавления одних и тех же хэндлеров
    # при повторных вызовах get_logger для одного и того же имени логгера.
    if not logger.handlers:
        # Хэндлер для записи логов в файл
        file_handler = RotatingFileHandler(
            os.path.join(LOG_DIR, LOG_FILE),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding='utf-8' # Добавлено явное указание кодировки для корректной работы с кириллицей
        )
        file_handler.setFormatter(LOG_FORMATTER)
        logger.addHandler(file_handler)

        # Хэндлер для вывода логов в консоль
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(LOG_FORMATTER)
        logger.addHandler(console_handler)

        # Отключаем распространение логов на родительские логгеры,
        # чтобы избежать двойного вывода, если корневой логгер также настроен.
        logger.propagate = False

    return logger