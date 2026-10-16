"""
SQLite база данных для хранения статей, очереди постов и расписания.
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import Optional

import config

logger = logging.getLogger(__name__)

# ── Инициализация ─────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Создать подключение к БД с row_factory для удобного доступа."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Создать таблицы, если их ещё нет."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,
                title_original TEXT NOT NULL,
                language TEXT DEFAULT 'en',
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS news_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_url TEXT NOT NULL,
                source TEXT NOT NULL,
                title_original TEXT NOT NULL,
                interest_score INTEGER DEFAULT 0,
                title_ru TEXT,
                body_ru TEXT,
                formatted_post TEXT,
                image_url TEXT,
                status TEXT DEFAULT 'pending',
                tg_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                published_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS daily_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                post_text TEXT,
                published BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_seen_url ON seen_articles(url);
            CREATE INDEX IF NOT EXISTS idx_queue_status ON news_queue(status);
            CREATE INDEX IF NOT EXISTS idx_schedule_date ON daily_schedule(date);
        """)
        
        # Миграция: добавляем image_url в существующую БД
        try:
            conn.execute("ALTER TABLE news_queue ADD COLUMN image_url TEXT;")
        except sqlite3.OperationalError:
            pass # Колонка уже существует

        conn.commit()
        logger.info("База данных инициализирована")
    finally:
        conn.close()


# ── seen_articles ─────────────────────────────────────────────────────

def is_article_seen(url: str) -> bool:
    """Проверить, была ли статья уже обработана."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM seen_articles WHERE url = ?", (url,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def mark_article_seen(
    url: str, source: str, title: str, language: str = "en"
) -> None:
    """Пометить статью как увиденную."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO seen_articles
               (url, source, title_original, language)
               VALUES (?, ?, ?, ?)""",
            (url, source, title, language),
        )
        conn.commit()
    finally:
        conn.close()


# ── news_queue ────────────────────────────────────────────────────────

def add_to_queue(
    article_url: str,
    source: str,
    title_original: str,
    interest_score: int,
    title_ru: Optional[str] = None,
    body_ru: Optional[str] = None,
    formatted_post: Optional[str] = None,
    image_url: Optional[str] = None,
    status: str = "pending",
) -> int:
    """Добавить статью в очередь. Возвращает ID записи."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO news_queue
               (article_url, source, title_original, interest_score,
                title_ru, body_ru, formatted_post, image_url, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                article_url, source, title_original, interest_score,
                title_ru, body_ru, formatted_post, image_url, status,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def get_pending_posts() -> list[sqlite3.Row]:
    """Получить все посты со статусом 'pending'."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM news_queue WHERE status = 'pending' ORDER BY interest_score DESC"
        ).fetchall()
    finally:
        conn.close()


def get_post_by_id(post_id: int) -> Optional[sqlite3.Row]:
    """Получить пост по ID."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM news_queue WHERE id = ?", (post_id,)
        ).fetchone()
    finally:
        conn.close()


def get_post_by_tg_message_id(tg_message_id: int) -> Optional[sqlite3.Row]:
    """Найти пост по ID сообщения в Telegram."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM news_queue WHERE tg_message_id = ?", (tg_message_id,)
        ).fetchone()
    finally:
        conn.close()


def update_post_status(
    post_id: int,
    status: str,
    tg_message_id: Optional[int] = None,
    formatted_post: Optional[str] = None,
) -> None:
    """Обновить статус поста и опционально message_id / текст."""
    conn = get_connection()
    try:
        parts = ["status = ?"]
        params: list = [status]

        if tg_message_id is not None:
            parts.append("tg_message_id = ?")
            params.append(tg_message_id)

        if formatted_post is not None:
            parts.append("formatted_post = ?")
            params.append(formatted_post)

        if status == "published":
            parts.append("published_at = ?")
            params.append(datetime.utcnow().isoformat())

        params.append(post_id)
        conn.execute(
            f"UPDATE news_queue SET {', '.join(parts)} WHERE id = ?", params
        )
        conn.commit()
    finally:
        conn.close()


def count_published_today() -> int:
    """Сколько постов опубликовано сегодня."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM news_queue WHERE status = 'published' AND DATE(published_at) = DATE('now')"
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def get_today_stats() -> dict:
    """Статистика за сегодня: получено, опубликовано, отклонено."""
    conn = get_connection()
    try:
        today = date.today().isoformat()
        fetched = conn.execute(
            "SELECT COUNT(*) as cnt FROM seen_articles WHERE DATE(fetched_at) = ?",
            (today,),
        ).fetchone()
        published = conn.execute(
            "SELECT COUNT(*) as cnt FROM news_queue WHERE status = 'published' AND DATE(published_at) = ?",
            (today,),
        ).fetchone()
        rejected = conn.execute(
            "SELECT COUNT(*) as cnt FROM news_queue WHERE status = 'rejected' AND DATE(created_at) = ?",
            (today,),
        ).fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) as cnt FROM news_queue WHERE status IN ('pending', 'sent_for_review')"
        ).fetchone()
        return {
            "fetched": fetched["cnt"] if fetched else 0,
            "published": published["cnt"] if published else 0,
            "rejected": rejected["cnt"] if rejected else 0,
            "pending": pending["cnt"] if pending else 0,
        }
    finally:
        conn.close()


# ── daily_schedule ────────────────────────────────────────────────────

def save_schedule(date_str: str, post_text: str) -> int:
    """Сохранить расписание дня. Возвращает ID."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO daily_schedule (date, post_text) VALUES (?, ?)",
            (date_str, post_text),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def mark_schedule_published(schedule_id: int) -> None:
    """Пометить расписание как опубликованное."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE daily_schedule SET published = 1 WHERE id = ?",
            (schedule_id,),
        )
        conn.commit()
    finally:
        conn.close()


def get_today_schedule() -> Optional[sqlite3.Row]:
    """Получить расписание на сегодня."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM daily_schedule WHERE date = ? ORDER BY id DESC LIMIT 1",
            (date.today().isoformat(),),
        ).fetchone()
    finally:
        conn.close()
