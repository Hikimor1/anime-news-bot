"""
Планировщик: периодический запуск парсинга, генерация расписания.
Использует APScheduler для cron-задач.

Основные функции (run_fetch_cycle, run_schedule_post) — async,
чтобы вызывать Telegram API напрямую.
"""

import asyncio
import logging
from datetime import date, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot

import config
import database as db
import ai_processor as ai
from sources import fetch_all_sources, fetch_today_schedule, fetch_top_episodes
from telegram_bot import send_for_review, send_banner_for_review

logger = logging.getLogger(__name__)


# ── Цикл парсинга ────────────────────────────────────────────────────

async def run_fetch_cycle(bot: Bot) -> None:
    """
    Основной цикл:
    1. Парсим все источники
    2. Фильтруем уже виденные
    3. Оцениваем каждую новость через AI
    4. Генерируем пост для интересных
    5. Отправляем на ревью админу
    """
    logger.info("=== Запуск цикла парсинга ===")

    # Парсинг в отдельном потоке (блокирующие HTTP-запросы)
    loop = asyncio.get_event_loop()
    articles = await loop.run_in_executor(None, fetch_all_sources)

    new_count = 0
    sent_count = 0

    for article in articles:
        # Пропускаем уже виденные
        if db.is_article_seen(article.url):
            continue

        # Помечаем как виденную
        db.mark_article_seen(
            url=article.url,
            source=article.source,
            title=article.title,
            language=article.language,
        )
        new_count += 1

        # Оценка интересности (блокирующий вызов OpenAI)
        score = await loop.run_in_executor(
            None, ai.score_interest, article.title, article.summary, article.source
        )
        logger.info(
            "  [%s] %s — score: %d",
            article.source, article.title[:60], score,
        )

        if score < config.INTEREST_THRESHOLD:
            # Сохраняем в БД, но не отправляем на ревью
            db.add_to_queue(
                article_url=article.url,
                source=article.source,
                title_original=article.title,
                interest_score=score,
                status="rejected",  # автоматически отклонена из-за низкого балла
            )
            continue

        # Проверяем лимит публикаций за день
        if db.count_published_today() >= config.MAX_POSTS_PER_DAY:
            logger.info("Достигнут лимит публикаций на сегодня, пропускаем")
            break

        # Генерация поста
        formatted = await loop.run_in_executor(
            None,
            ai.translate_and_format,
            article.title,
            article.summary,
            article.url,
            article.language,
        )

        if not formatted:
            logger.warning("Не удалось сгенерировать пост для: %s", article.title)
            continue

        # Сохраняем в БД
        post_id = db.add_to_queue(
            article_url=article.url,
            source=article.source,
            title_original=article.title,
            interest_score=score,
            formatted_post=formatted,
            image_url=article.image_url,
            status="pending",
        )

        # Отправляем на ревью
        success = await send_for_review(bot, post_id, formatted, article.source, score, image_url=article.image_url)
        if success:
            sent_count += 1

    logger.info(
        "=== Цикл завершён: новых %d, отправлено на ревью %d ===",
        new_count, sent_count,
    )


# ── Пост расписания ──────────────────────────────────────────────────

async def run_schedule_post(bot: Bot) -> None:
    """Получить расписание на сегодня и опубликовать/отправить на ревью."""
    logger.info("=== Генерация расписания ===")

    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(None, fetch_today_schedule)

    if not entries:
        logger.info("Расписание пусто, пропускаем")
        return

    anime_list = [
        {
            "title": e.title,
            "episode": e.episode,
            "anime_type": e.anime_type,
            "rating": e.rating,
        }
        for e in entries
    ]

    post_text = await loop.run_in_executor(
        None, ai.generate_schedule_post, anime_list
    )

    if not post_text:
        logger.warning("Не удалось сгенерировать пост расписания")
        return

    # Сохраняем в очередь и отправляем на ревью
    post_id = db.add_to_queue(
        article_url=f"schedule:{date.today().isoformat()}",
        source="YummyAnime Расписание",
        title_original=f"Расписание аниме на {date.today().strftime('%d.%m.%Y')}",
        interest_score=10,
        formatted_post=post_text,
        status="pending",
    )

    success = await send_for_review(bot, post_id, post_text, "YummyAnime Расписание", 10)
    if success:
        logger.info("Расписание отправлено на ревью")
    else:
        logger.error("Не удалось отправить расписание на ревью")


# ── Еженедельный баннер ──────────────────────────────────────────────

def _format_banner_caption(entries: list, week: int) -> str:
    month = datetime.now().month
    season_map = {12: "Зима", 1: "Зима", 2: "Зима",
                  3: "Весна", 4: "Весна", 5: "Весна",
                  6: "Лето", 7: "Лето", 8: "Лето"}
    season = season_map.get(month, "Осень")
    year = datetime.now().year

    lines = [f"🏆 Топ-{len(entries)} эпизодов недели • Неделя {week} • {season} {year}\n"]
    for i, e in enumerate(entries, 1):
        lines.append(f"{i}. «{e.title}» — {e.episode_info} ⭐ {e.rating}")
    lines.append(f"\n{config.POST_SIGNATURE}")
    return "\n".join(lines)


async def run_weekly_banner(bot: Bot) -> None:
    """Получить топ-6 аниме, сгенерировать 2 баннера и отправить на ревью."""
    logger.info("=== Генерация еженедельного баннера ===")

    loop = asyncio.get_event_loop()

    entries = await loop.run_in_executor(None, fetch_top_episodes, 6)
    if not entries:
        logger.warning("Не удалось получить топ-эпизоды для баннера")
        return

    from image_generator import ImageGenerator, EpisodeData
    episodes = [
        EpisodeData(
            rank=i + 1,
            title=entry.title.upper(),
            genres=entry.genres,
            episode_info=entry.episode_info,
            rating=str(entry.rating),
            # bannerImage (широкий) в приоритете, fallback — coverImage (портрет)
            image_url=entry.banner_image_url or entry.cover_image_url,
        )
        for i, entry in enumerate(entries)
    ]

    gen = ImageGenerator()
    banner_paths = await loop.run_in_executor(None, gen.generate_banner_pair, episodes)

    if not banner_paths:
        logger.error("Не удалось сгенерировать баннеры")
        return

    week = datetime.now().isocalendar()[1]
    caption = _format_banner_caption(entries, week)

    await send_banner_for_review(bot, banner_paths, caption)
    logger.info("Еженедельный баннер отправлен на ревью")


# ── Настройка планировщика ────────────────────────────────────────────

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Создать и настроить APScheduler с задачами."""
    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

    # Парсинг новостей — каждые N часов
    scheduler.add_job(
        run_fetch_cycle,
        trigger=IntervalTrigger(hours=config.FETCH_INTERVAL_HOURS),
        args=[bot],
        id="fetch_cycle",
        name="Цикл парсинга новостей",
        replace_existing=True,
    )

    # Расписание — ежедневно в SCHEDULE_POST_HOUR МСК
    scheduler.add_job(
        run_schedule_post,
        trigger=CronTrigger(hour=config.SCHEDULE_POST_HOUR, minute=0),
        args=[bot],
        id="daily_schedule",
        name="Ежедневное расписание",
        replace_existing=True,
    )

    # Еженедельный баннер — каждый понедельник в WEEKLY_BANNER_HOUR МСК
    scheduler.add_job(
        run_weekly_banner,
        trigger=CronTrigger(day_of_week="mon", hour=config.WEEKLY_BANNER_HOUR, minute=0),
        args=[bot],
        id="weekly_banner",
        name="Еженедельный баннер топ-6 эпизодов",
        replace_existing=True,
    )

    logger.info(
        "Планировщик настроен: парсинг каждые %dч, расписание в %d:00, баннер по понедельникам в %d:00 %s",
        config.FETCH_INTERVAL_HOURS,
        config.SCHEDULE_POST_HOUR,
        config.WEEKLY_BANNER_HOUR,
        config.TIMEZONE,
    )

    return scheduler
