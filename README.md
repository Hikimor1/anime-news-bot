# 🎌 Anime News Bot

Telegram-бот для автоматической агрегации аниме-новостей, оценки их интересности через AI и публикации в канал с ручной модерацией.

## Что делает бот

1. **Парсит новости** из 11 источников (RSS, веб-скрейпинг, API)
2. **Оценивает интересность** каждой новости через AI (Gemini / Groq / OpenAI)
3. **Переводит и форматирует** посты в стиле канала
4. **Отправляет на ревью** админу с кнопками «Опубликовать / Редактировать / Отклонить»
5. **Публикует** одобренные посты в Telegram-канал
6. **Генерирует расписание** выходящих аниме на каждый день

## Бесплатные LLM-провайдеры

Бот работает с тремя LLM-провайдерами через единый OpenAI-совместимый SDK. Карта не нужна ни для одного из бесплатных:

| Провайдер | Модель | Лимит (free) | Получить ключ |
|-----------|--------|--------------|---------------|
| **Gemini** (рекомендуется) | gemini-2.5-flash | 250 запр/день | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Groq** (очень быстрый) | llama-3.3-70b | 1000 запр/день | [console.groq.com/keys](https://console.groq.com/keys) |
| OpenAI (платный) | gpt-4o-mini | по балансу | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |

**Рекомендуемая схема:** Gemini как основной + Groq как фоллбэк. Бот автоматически переключится на запасной провайдер при rate limit.

При 6 постах в день бот делает ~50-80 запросов к LLM (оценка + генерация). Это легко укладывается в бесплатные лимиты Gemini (250/день) или Groq (1000/день).

## Установка

### 1. Клонирование и зависимости

```bash
cd /путь/к/проекту
pip install -r requirements.txt
```

Требуется Python 3.10+.

### 2. Настройка config.py

Откройте `config.py` и заполните:

```python
TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."  # от @BotFather
ADMIN_CHAT_ID = 123456789                  # ваш Telegram ID
CHANNEL_ID = "@your_channel"               # канал для публикации

# LLM — выберите провайдер
LLM_PROVIDER = "gemini"                    # gemini | groq | openai
GEMINI_API_KEY = "AIza..."                 # бесплатно
GROQ_API_KEY = "gsk_..."                   # бесплатно (как фоллбэк)
```

Альтернативно, задайте переменные окружения:
```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export ADMIN_CHAT_ID="123456789"
export CHANNEL_ID="@your_channel"
export LLM_PROVIDER="gemini"
export GEMINI_API_KEY="AIza..."
export GROQ_API_KEY="gsk_..."
```

### 3. Создание Telegram-бота

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Выберите имя и username
4. Скопируйте токен в `config.py`
5. Добавьте бота **администратором** в ваш канал (с правом публикации)

### 4. Узнать свой ADMIN_CHAT_ID

Отправьте любое сообщение боту [@userinfobot](https://t.me/userinfobot) — он покажет ваш ID.

## Запуск

```bash
cd anime_news_bot
python main.py
```

Бот:
- Создаст SQLite базу `anime_news.db`
- Выполнит первый цикл парсинга
- Начнёт polling для Telegram-команд
- Будет парсить новости каждые 2 часа
- Будет публиковать расписание в 10:00 МСК

## Команды бота

| Команда      | Описание                          |
|-------------|-----------------------------------|
| `/start`    | Приветствие и список команд       |
| `/pending`  | Количество постов в очереди       |
| `/stats`    | Статистика за сегодня             |
| `/fetch`    | Принудительный запуск парсинга    |
| `/schedule` | Сгенерировать расписание          |

## Systemd-сервис (автозапуск)

Создайте файл `/etc/systemd/system/anime-news-bot.service`:

```ini
[Unit]
Description=Anime News Telegram Bot
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/anime_news_bot
ExecStart=/opt/anime_news_bot/venv/bin/python main.py
Restart=always
RestartSec=10

# Переменные окружения
Environment=TELEGRAM_BOT_TOKEN=your_token_here
Environment=ADMIN_CHAT_ID=your_id_here
Environment=CHANNEL_ID=@your_channel
Environment=LLM_PROVIDER=gemini
Environment=GEMINI_API_KEY=your_gemini_key
Environment=GROQ_API_KEY=your_groq_key

# Логирование
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Установка:
```bash
# Копируем проект
sudo cp -r anime_news_bot /opt/anime_news_bot

# Создаём venv
cd /opt/anime_news_bot
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt

# Включаем сервис
sudo systemctl daemon-reload
sudo systemctl enable anime-news-bot
sudo systemctl start anime-news-bot

# Просмотр логов
sudo journalctl -u anime-news-bot -f
```

## Как работает фоллбэк

Если основной провайдер вернул ошибку (rate limit, таймаут), бот автоматически пробует следующий провайдер из списка `FALLBACK_PROVIDERS`. Порядок по умолчанию:

1. Gemini → 2. Groq → 3. OpenAI

Провайдеры без заполненного API-ключа пропускаются.

## Добавление новых источников

### RSS-источник

В `config.py` добавьте в `RSS_SOURCES`:

```python
{
    "name": "НазваниеИсточника",
    "url": "https://example.com/feed.xml",
    "language": "en",  # или "ja", "ru"
},
```

### Веб-источник (скрейпинг)

1. В `sources.py` создайте функцию `_scrape_your_source()`:

```python
def _scrape_your_source() -> list[Article]:
    url = "https://example.com/news"
    resp = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT)
    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []
    for item in soup.select("ваш CSS-селектор"):
        articles.append(Article(
            url=item["href"],
            title=item.get_text(strip=True),
            summary="",
            source="YourSource",
            language="en",
        ))
    return articles
```

2. Добавьте в словарь `scrapers` внутри `fetch_all_web()`.

## Структура проекта

```
anime_news_bot/
├── config.py          # Настройки, API-ключи, провайдеры, пороги
├── database.py        # SQLite: статьи, очередь, расписание
├── sources.py         # RSS/веб-фетчеры для каждого источника
├── ai_processor.py    # Мультипровайдер LLM: оценка, перевод, форматирование
├── telegram_bot.py    # Telegram: ревью + публикация
├── scheduler.py       # APScheduler: периодические задачи
├── main.py            # Точка входа
├── requirements.txt
└── README.md
```

## Настраиваемые параметры

| Параметр               | По умолчанию    | Описание                         |
|------------------------|-----------------|----------------------------------|
| `LLM_PROVIDER`         | gemini          | Основной LLM-провайдер           |
| `INTEREST_THRESHOLD`   | 6               | Минимальный балл для ревью       |
| `MAX_POSTS_PER_DAY`    | 6               | Лимит публикаций в день          |
| `FETCH_INTERVAL_HOURS` | 2               | Интервал парсинга (часы)         |
| `SCHEDULE_POST_HOUR`   | 10              | Час публикации расписания (МСК)  |
| `REQUEST_TIMEOUT`      | 15              | Таймаут HTTP-запросов (сек)      |
