import re
from core.logger import get_logger
from typing import Tuple  # Добавляем для более точной типизации кортежей

logger = get_logger("validator")


class QueryValidator:
    def __init__(self, min_length: int = 3):
        self.min_length = min_length
        # Паттерны для определения недопустимых запросов
        self.invalid_patterns = [
            (r'^/\w+', "Ваш запрос выглядит как команда бота. Пожалуйста, введите обычный текст."),
            (r'^\d+$', "Ваш запрос состоит только из цифр. Пожалуйста, опишите, что вы ищете."),
            (r'^[^\w\s]+$',
             "Ваш запрос состоит только из специальных символов. Пожалуйста, введите осмысленный текст."),
            (r'^\s*$', "Ваш запрос пуст. Пожалуйста, введите что-нибудь.")  # Добавлено для пустых строк
        ]

    def is_valid(self, query: str) -> bool:
        """
        Проверяет, является ли запрос пользователя допустимым.

        Проверки включают:
        1. Достаточную длину запроса.
        2. Отсутствие совпадений с предопределенными недопустимыми паттернами (команды бота, только числа, только спецсимволы).

        Args:
            query: Строка запроса пользователя.

        Returns:
            True, если запрос допустим, иначе False.
        """
        cleaned_query = query.strip()

        if len(cleaned_query) < self.min_length:
            return False

        for pattern, _ in self.invalid_patterns:  # Теперь итерируемся по кортежам
            if re.fullmatch(pattern, cleaned_query):  # Изменено на fullmatch для более строгой проверки
                return False

        return True

    def get_invalid_reason(self, query: str) -> str:
        """
        Возвращает объяснение, почему запрос считается недопустимым, в удобочитаемом формате.

        Args:
            query: Строка запроса пользователя.

        Returns:
            Строка с причиной недопустимости запроса.
        """
        cleaned_query = query.strip()

        if len(cleaned_query) < self.min_length:
            return f"Ваш запрос слишком короткий. Он должен содержать минимум {self.min_length} символа(ов)."

        # Специальная проверка для пустой строки, если min_length = 0 или 1
        if not cleaned_query:
            return "Ваш запрос пуст. Пожалуйста, введите что-нибудь."

        for pattern, reason in self.invalid_patterns:
            if re.fullmatch(pattern, cleaned_query):  # Изменено на fullmatch
                return reason

        # Это должно быть достигнуто только если is_valid вернул False, но ни один паттерн не совпал
        # (что в идеале не должно происходить при правильных паттернах и логике)
        return "Неизвестная причина. Ваш запрос не может быть обработан."

    def validate_or_explain(self, query: str) -> Tuple[bool, str]:
        """
        Проверяет запрос и возвращает кортеж: (является ли запрос допустимым, причина, если нет).

        Args:
            query: Строка запроса пользователя.

        Returns:
            Кортеж (bool, str), где bool указывает на допустимость, а str - на причину
            (пустая строка, если запрос допустим).
        """
        if self.is_valid(query):
            return True, ""
        return False, self.get_invalid_reason(query)

    def validate_and_log(self, query: str) -> bool:
        """
        Проверяет запрос и логирует предупреждение, если запрос отклонен.

        Args:
            query: Строка запроса пользователя.

        Returns:
            True, если запрос допустим, иначе False.
        """
        is_valid, reason = self.validate_or_explain(query)
        if not is_valid:
            logger.warning(f"Отклонённый запрос: '{query}'. Причина: {reason}")
            return False
        return True