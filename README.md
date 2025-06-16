# 🎬 RecomenDashka — Telegram Movie Recommendation Bot

Телеграм-бот, который использует возможности языковых моделей (LLM) для персонализированной рекомендации фильмов и общения о кино.

---

## 🚀 Возможности

- 🎥 Рекомендации фильмов на основе текстовых запросов
- 💬 Обсуждение содержания фильмов
- 🧠 Использование LLM (Gemini API) для анализа предпочтений
- 🗂️ Работа с базой данных фильмов (описания, жанры и др.)
- 🔍 Поиск похожих фильмов на основе запроса или примера
- 📝 История взаимодействия и персонализация

---

## 🧩 Используемые технологии

- Язык: Python
- LLM: Google Gemini (через Gemini API)
- API фильмов: [TMDB](https://www.themoviedb.org/)
- Telegram API: [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- Хранение данных: SQLite
- Переменные окружения: `dotenv`

---

## 🛠 Установка и запуск

### 1. Клонировать проект:

```bash
git clone https://github.com/RecomenDashka/MainDuane.git
cd MainDuane
```

### 2. Установить зависимости:
Если используете виртуальное окружение:

```bash
python -m venv .venv
source .venv/bin/activate  # для Linux/macOS
.venv\Scripts\activate  # для Windows
```
 Затем установите зависимости:

```bash
pip install -r requirements.txt
````
### 3. Настроить переменные окружения:
Создайте файл .env на основе шаблона:

```bash
cp env.example .env
```
Откройте .env и укажите свои ключи:

```bash
TELEGRAM_BOT_TOKEN=ваш_токен_от_BotFather
GEMINI_API_KEY=ваш_API_ключ_от_Google_Gemini
TMDB_API_KEY=ваш_API_ключ_от_TMDb
DATABASE_PATH=movie_bot.db
```
🔐 Что такое .env и как он работает
Файл .env используется для хранения чувствительных данных, которые нельзя публиковать в GitHub.

✅ .env добавлен в .gitignore — он остаётся у вас локально.

В коде файл подключается через:

```bash
from dotenv import load_dotenv
import os

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN")
```
---
## 📝 Примеры использования
Запросы, которые понимает бот:

"Посоветуй боевик с крутыми спецэффектами"

"Хочу посмотреть что-то вроде «Интерстеллар»"

"Обсудим «Матрицу», я не понял концовку"

"Порекомендуй 3 комедии на вечер"

"Какие фантастические фильмы вышли после 2019?"

## 💡 Команды бота
### Команда	Описание:
/start Приветствие и начало <br>
/help	Справка по использованию<br>
/preferences	Настройка предпочтений пользователя<br>
/popular	Популярные фильмы<br>
/similar	Найти похожие фильмы<br>

## 📦 Структура проекта
```bash
MainDuane/
├── main.py                   # Основной скрипт Telegram-бота
├── recommendation.py         # Генерация рекомендаций через LLM
├── requirements.txt          # Зависимости проекта
├── env.example               # Шаблон конфигурационного файла
├── .gitignore                # Исключения для Git (в т.ч. .env)
├── movie_bot.db              # Локальная база данных
├── movie_recommendations.db  # База рекомендаций
├── README.md                 # Описание проекта
```

## 👥 Участники проекта
Команда RecomenDashka:

 Гусейнов Гумбатали (LLM, рекомендации)

 Алов Владислав (база данных, история запросов)

 Лачина София (интеграция с TMDB, обработка данных)

 Путилов Илья (Telegram-интерфейс и команды)

