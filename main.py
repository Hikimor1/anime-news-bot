#!/usr/bin/env python3
"""
Anime News Bot — точка входа.

Инициализирует БД, настраивает логирование, запускает планировщик
и Telegram-бота через run_polling().
"""

import logging
import sys

from telegram.ext import Application

import config
import database as db
from scheduler import setup_scheduler, run_fetch_cycle
from telegram_bot import create_application


def setup_logging() -> None:
    """Настроить логирование в файл и консоль."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(config.LOG_FORMAT)

    # Консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Файл
    file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Приглушаем шумные библиотеки
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


def validate_config() -> bool:
    """Проверить, что ключевые настройки заполнены."""
    errors = []
    if config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN" or not config.TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN не настроен")
    if config.ADMIN_CHAT_ID == 0:
        errors.append("ADMIN_CHAT_ID не настроен")

    # Проверяем, есть ли хотя бы один LLM-провайдер с ключом
    has_llm = any([
        config.GEMINI_API_KEY,
        config.GROQ_API_KEY,
        config.OPENAI_API_KEY,
    ])
    if not has_llm:
        errors.append(
            "Нет ни одного LLM API-ключа! Заполните хотя бы один:\n"
            "  GEMINI_API_KEY (бесплатно): https://aistudio.google.com/apikey\n"
            "  GROQ_API_KEY (бесплатно):   https://console.groq.com/keys\n"
            "  OPENAI_API_KEY (платно):     https://platform.openai.com/api-keys"
        )
    else:
        # Предупреждаем, если основной провайдер без ключа
        provider = config.LLM_PROVIDER
        provider_keys = {
            "gemini": config.GEMINI_API_KEY,
            "groq": config.GROQ_API_KEY,
            "openai": config.OPENAI_API_KEY,
        }
        if not provider_keys.get(provider):
            logging.warning(
                "Основной провайдер '%s' не имеет API-ключа, будет использован фоллбэк",
                provider,
            )

    if errors:
        for e in errors:
            logging.error("Ошибка конфигурации: %s", e)
        return False

    logging.info("LLM-провайдер: %s (фоллбэк: %s)", config.LLM_PROVIDER, config.FALLBACK_PROVIDERS)
    return True


async def post_init(app: Application) -> None:
    """Хук post_init: запускает планировщик и первый цикл парсинга после инициализации бота."""
    logger = logging.getLogger(__name__)
    bot = app.bot  # используем бот из Application, а не создаём отдельный

    # Настраиваем планировщик
    global _scheduler
    _scheduler = setup_scheduler(bot)
    _scheduler.start()
    logger.info("Планировщик запущен")

    # Первый цикл парсинга
    logger.info("Запускаем начальный цикл парсинга...")
    try:
        await run_fetch_cycle(bot)
    except Exception as e:
        logger.error("Ошибка при начальном цикле парсинга: %s", e)


_scheduler = None  # глобальная ссылка на планировщик


def main() -> None:
    """Основная функция: запуск бота + планировщика."""
    logger = logging.getLogger(__name__)

    # Инициализация БД
    db.init_db()
    logger.info("БД инициализирована: %s", config.DB_PATH)

    # Создаём Telegram Application с post_init хуком
    app = create_application(post_init=post_init)

    logger.info("Запускаем Telegram-бота...")

    # run_polling() сам управляет initialize/start/stop/shutdown
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 50)
    logger.info("Anime News Bot запускается...")
    logger.info("=" * 50)

    if not validate_config():
        logger.error("Исправьте ошибки конфигурации в config.py или переменных окружения")
        sys.exit(1)

    try:
        main()
    except KeyboardInterrupt:
        logger.info("Завершение по Ctrl+C")
