# agents/llm_generator.py

import httpx
import random
import asyncio  # Добавлено для asyncio.sleep
from typing import Dict, Any, Optional  # Добавлено для более точной типизации
from core.logger import get_logger

logger = get_logger(__name__)


class LLMGenerator:
    def __init__(self, api_key: str, model: str = "mistralai/mistral-7b-instruct"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        # Рекомендуется создавать один экземпляр httpx.AsyncClient для переиспользования
        # self.client = httpx.AsyncClient(timeout=15.0)

    async def generate(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.7, max_tokens: Optional[int] = None,
                       retries: int = 3, delay: int = 1) -> str:
        """
        Отправляет запрос к LLM (OpenRouter API) и возвращает сгенерированный текст.

        Args:
            prompt: Основной запрос пользователя.
            system_prompt: Системная инструкция для LLM.
            temperature: Температура генерации (от 0.0 до 1.0).
            max_tokens: Максимальное количество токенов в ответе.
            retries: Количество повторных попыток в случае ошибки API.
            delay: Начальная задержка между попытками (в секундах), удваивается при неудаче.

        Returns:
            Сгенерированный LLM текст или сообщение об ошибке в случае неудачи.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://recomendashka.app",  # Указываем источник запроса
            "X-Title": "RecomenDashka"  # Имя приложения
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        current_delay = delay
        for attempt in range(retries):
            try:
                logger.info(f"Sending prompt to LLM (attempt {attempt + 1}/{retries}): '{prompt[:100]}...'")
                # Используем async with для создания временного клиента
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(self.base_url, headers=headers, json=payload)
                    response.raise_for_status()  # Вызывает исключение для HTTP ошибок (4xx, 5xx)
                    result = response.json()

                    if "choices" in result and result["choices"] and "message" in result["choices"][0]:
                        return result["choices"][0]["message"]["content"].strip()
                    else:
                        logger.error(f"LLM API response missing 'choices' or 'message': {result}")
                        raise ValueError("Invalid LLM response format")  # Вызываем ошибку для повторной попытки
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"LLM HTTP error (attempt {attempt + 1}/{retries}): {e.response.status_code} - {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"LLM Request error (attempt {attempt + 1}/{retries}): {e}")
            except Exception as e:  # Ловим любые другие непредвиденные ошибки
                logger.error(f"LLM API call failed with unexpected error (attempt {attempt + 1}/{retries}): {e}")

            if attempt < retries - 1:
                await asyncio.sleep(current_delay)
                current_delay *= 2  # Экспоненциальное увеличение задержки
            else:
                logger.error(
                    f"Failed to generate LLM response after {retries} attempts for prompt: '{prompt[:100]}...'")

        return "Извините, произошла ошибка при генерации ответа. Пожалуйста, попробуйте еще раз."