from typing import List, Dict, Any
from core.logger import get_logger

logger = get_logger("formatter")


def _truncate_text(text: str, max_length: int = 700, suffix: str = "...") -> str:
    """
    Усекает текст до заданной максимальной длины, добавляя суффикс, если текст был усечен.
    Учитывает, что Markdown-форматирование может добавить символы, поэтому max_length
    должен быть несколько меньше 1024 (общего лимита caption).
    """
    if not isinstance(text, str):
        return ""
    if len(text) <= max_length:
        return text

    # Пытаемся обрезать по последнему полному слову, чтобы избежать обрезки посреди слова
    truncated = text[:max_length]
    last_space = truncated.rfind(' ')
    if last_space != -1:
        return truncated[:last_space] + suffix
    return truncated + suffix


def format_movie(movie: Dict[str, Any]) -> str:
    """
    Преобразует словарь с данными о фильме в читаемый Markdown-текст для Telegram.
    Использует поля из словаря movie и форматирует их.
    """
    title = movie.get("title", "Без названия")
    # Усекаем описание, чтобы не превышать лимит подписи Telegram
    overview = _truncate_text(movie.get("overview", "Описание недоступно."))

    rating = f"{movie.get('vote_average', 0):.1f}" if movie.get('vote_average') is not None else "–"

    release_date_full = movie.get("release_date", "")
    release_year = release_date_full.split('-')[0] if release_date_full and len(release_date_full) >= 4 else "–"

    genres = ", ".join(movie.get("genres", [])) if isinstance(movie.get("genres"), list) else movie.get("genres", "–")

    runtime_val = movie.get("runtime")
    runtime = f"{runtime_val} мин" if isinstance(runtime_val, (int, float)) else "–"

    directors = ", ".join([d['name'] for d in movie.get("directors", [])]) if isinstance(movie.get("directors"),
                                                                                         list) and movie.get(
        "directors") else "–"
    actors = ", ".join([a['name'] for a in movie.get("actors", [])]) if isinstance(movie.get("actors"),
                                                                                   list) and movie.get(
        "actors") else "–"

    # Форматирование для вывода в Telegram (MarkdownV2)
    # Используем os.linesep для кроссплатформенности, но Telegram обычно понимает \n
    lines = [
        f"🎬 *{title}* ({release_year})",
        f"⭐ Рейтинг: `{rating}/10`",
        f"🎭 Жанры: {genres}",
        f"⏳ Длительность: {runtime}",
        f"👨‍ directorial: {directors}",
        f"👥 В ролях: {actors}",
        f"",  # Пустая строка для отступа
        f"📝 *Описание:* {overview}"
    ]

    formatted_text = "\n".join(lines)
    logger.info(f"Сформированы детали фильма для Telegram: {title}")
    return formatted_text


def format_movies_list(movies: List[Dict[str, Any]]) -> str:
    """
    Форматирует список фильмов в кратком виде (например, для истории или топов)
    с использованием Markdown.

    Args:
        movies: Список словарей с данными о фильмах.

    Returns:
        Отформатированная строка для вывода в Telegram.
    """
    if not movies:
        return "Список фильмов пуст."

    lines = []
    for idx, movie in enumerate(movies, 1):
        title = movie.get("title", "Без названия")
        rating = f"{movie.get('vote_average', 0):.1f}" if movie.get('vote_average') is not None else "–"
        release_date_full = movie.get("release_date", "")
        release_year = release_date_full.split('-')[0] if release_date_full and len(release_date_full) >= 4 else "–"

        lines.append(f"{idx}. *{title}* — {release_year}, ⭐ {rating}/10")
    logger.info(f"Сформирован список фильмов для Telegram: {len(movies)} шт.")
    return "\n".join(lines)


def format_llm_response(response: str) -> str:
    """
    Делает LLM-ответ пригодным для Telegram, добавляя вводную фразу и форматирование.

    Args:
        response: Сырой текст ответа от LLM.

    Returns:
        Отформатированная строка с Markdown.
    """
    # Удаляем лишние пробелы в начале/конце и добавляем Markdown
    formatted_response = f"📢 *Рекомендации для вас:*\n\n{response.strip()}"
    logger.info("Ответ LLM отформатирован.")
    return formatted_response


def format_error(message: str) -> str:
    """
    Форматирует сообщение об ошибке для пользователя.
    """
    return f"❌ Произошла ошибка: *{message}*\n\nПожалуйста, попробуйте еще раз."
