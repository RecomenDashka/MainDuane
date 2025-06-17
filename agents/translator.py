import asyncio
from agents.llm_generator import LLMGenerator
from core.logger import get_logger
from typing import Optional, List
import re
import difflib

logger = get_logger(__name__)


class TranslatorAgent:
    def __init__(self, llm_generator: LLMGenerator):
        self.llm = llm_generator

    def _clean_llm_response(self, text: str, for_language_detection: bool = False) -> str:
        """
        Очищает ответ LLM от шаблонных фраз и лишних пояснений.
        Args:
            text: Исходный текст от LLM.
            for_language_detection: Если True, применяется более строгая очистка для кодов языка.
        """
        if not isinstance(text, str):
            return ""

        text = text.strip()

        if for_language_detection:
            # Сначала пытаемся найти ровно две буквы, окруженные границами слов или не буквенными символами
            match = re.search(r'\b([a-z]{2})\b', text.lower())
            if match:
                return match.group(1)

            # Если не найдено, пробуем более гибко: ищем две буквы подряд
            match = re.search(r'([a-z]{2})', text.lower())
            if match:
                return match.group(1)

            # Если совсем ничего не нашли, возвращаем пустую строку
            return ""

        else:
            # Общая очистка для переведенного текста (без изменения регистра)
            text = re.sub(r'^(Translation|Перевод|English|Russian|Текст|:)\s*[\'"]?|\s*[\'"]?\s*$', '', text,
                          flags=re.IGNORECASE).strip()
            text = re.sub(r'\(.*?\)', '', text).strip()  # Удаляем текст в скобках
            text = re.sub(r'[«»"]', '', text).strip()  # Удаляем специфические кавычки
            return text.strip()

    async def translate_to_english(self, russian_text: str, retries: int = 3, delay: int = 1) -> str:
        """
        Переводит русский текст на английский язык с поддержкой повторных попыток.
        """
        prompt = (
            "You are a professional translator. Translate the following Russian text into fluent English. "
            "Provide ONLY the translated text, without any additional explanations, formatting, or conversational phrases."
            f"Russian: {russian_text}\\nEnglish:"
        )
        current_delay = delay
        for attempt in range(retries):
            try:
                translation = await self.llm.generate(prompt)
                cleaned_translation = self._clean_llm_response(translation)
                if cleaned_translation:
                    return cleaned_translation
            except Exception as e:
                logger.warning(f"Translation to English failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(current_delay)
                current_delay *= 2
        logger.error(f"Failed to translate Russian text to English after {retries} attempts: '{russian_text[:100]}...'")
        return russian_text

    async def translate_to_russian(self, english_text: str, retries: int = 3, delay: int = 1) -> str:
        """
        Переводит английский текст на русский язык с поддержкой повторных попыток.
        """
        prompt = (
            "You are a professional translator. Translate the following English text into fluent Russian. "
            "Provide ONLY the translated text, without any additional explanations, formatting, or conversational phrases."
            f"English: {english_text}\\nRussian:"
        )
        current_delay = delay
        for attempt in range(retries):
            try:
                translation = await self.llm.generate(prompt)
                cleaned_translation = self._clean_llm_response(translation)
                if cleaned_translation:
                    return cleaned_translation
            except Exception as e:
                logger.warning(f"Translation to Russian failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(current_delay)
                current_delay *= 2
        logger.error(f"Failed to translate English text to Russian after {retries} attempts: '{english_text[:100]}...'")
        return english_text

    async def detect_language(self, text: str, retries: int = 3, delay: int = 1) -> Optional[str]:
        """
        Определяет язык текста и возвращает его ISO 639-1 код (например, 'en', 'ru').
        Возвращает только код языка, без дополнительных пояснений.
        """
        if not text:
            return None

        prompt = (
            "Detect the language of the following text and return ONLY the ISO 639-1 code "
            "(e.g., 'en', 'ru', 'fr', 'de'). Do NOT provide any additional explanations, "
            "phrases like 'The language is', or parentheses. Just the two-letter code."
            f"Text: \"{text}\""
        )
        current_delay = delay
        for attempt in range(retries):
            try:
                lang_code = await self.llm.generate(prompt)
                cleaned_lang_code = self._clean_llm_response(lang_code, for_language_detection=True)

                if cleaned_lang_code and len(cleaned_lang_code) == 2 and cleaned_lang_code.isalpha():
                    return cleaned_lang_code
                else:
                    logger.warning(
                        f"LLM returned invalid language code: '{lang_code}' for text '{text[:50]}...' after cleaning: '{cleaned_lang_code}'")
                    return None
            except Exception as e:
                logger.warning(
                    f"Language detection error for text '{text[:50]}...' (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(current_delay)
                current_delay *= 2
        logger.error(f"Failed to detect language after {retries} attempts for text: '{text[:100]}...'")
        return None

    def is_translation_different(self, original_text: str, translated_text: str) -> bool:
        """
        Проверяет, является ли переведенный текст существенно отличающимся от оригинала,
        используя нечеткое сравнение. Это помогает понять, был ли перевод
        действительно выполнен или LLM просто вернула оригинал.
        """
        if not original_text or not translated_text:
            return False

        cleaned_original = self._clean_llm_response(original_text).lower()
        cleaned_translated = self._clean_llm_response(translated_text).lower()

        return cleaned_original != cleaned_translated and \
            difflib.SequenceMatcher(None, cleaned_original, cleaned_translated).ratio() < 0.95

    async def translate_batch(self, texts: List[str], target_language: str) -> List[str]:
        """
        Переводит список текстов в пакетном режиме.
        """
        translated_texts = []
        if target_language.lower() == "english":
            for text in texts:
                translated_texts.append(await self.translate_to_english(text))
        elif target_language.lower() == "russian":
            for text in texts:
                translated_texts.append(await self.translate_to_russian(text))
        else:
            logger.warning(f"Unsupported target language for batch translation: {target_language}")
            return texts
        return translated_texts

