"""
Фетчеры новостей: RSS (feedparser), веб-скрейпинг (requests + BS4),
и API расписания (AnimeSchedule).
"""

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


@dataclass
class Article:
    """Унифицированная модель статьи из любого источника."""
    url: str
    title: str
    summary: str
    source: str
    language: str
    image_url: Optional[str] = None


# ── RSS-фетчер ────────────────────────────────────────────────────────

def fetch_rss(source: dict) -> list[Article]:
    """Получить статьи из RSS/Atom-фида."""
    name = source["name"]
    url = source["url"]
    lang = source.get("language", "en")

    logger.info("Fetching RSS: %s (%s)", name, url)
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        if feed.bozo and not feed.entries:
            logger.warning("RSS parse error for %s: %s", name, feed.bozo_exception)
            return []

        articles = []
        for entry in feed.entries[:20]:  # берём последние 20
            link = entry.get("link", "")
            title = entry.get("title", "").strip()
            # summary может быть HTML — берём text
            raw_summary = entry.get("summary", entry.get("description", ""))
            summary = _strip_html(raw_summary)[:500]

            # Ищем изображение в RSS (media:thumbnail, media:content или внутри HTML)
            image_url = None
            if "media_thumbnail" in entry and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url")
            elif "media_content" in entry and entry.media_content:
                for media in entry.media_content:
                    if media.get("medium") == "image":
                        image_url = media.get("url")
                        break
            
            # Если не нашли в специальных тегах, парсим HTML summary
            if not image_url and raw_summary:
                soup = BeautifulSoup(raw_summary, "html.parser")
                img = soup.find("img")
                if img and img.get("src"):
                    image_url = img["src"]

            if not link or not title:
                continue

            articles.append(Article(
                url=link,
                title=title,
                summary=summary,
                source=name,
                language=lang,
                image_url=image_url,
            ))

        logger.info("  %s: получено %d статей", name, len(articles))
        return articles

    except Exception as e:
        logger.error("Ошибка при парсинге RSS %s: %s", name, e)
        return []


def fetch_all_rss() -> list[Article]:
    """Получить статьи из всех RSS-источников."""
    all_articles: list[Article] = []
    for source in config.RSS_SOURCES:
        articles = fetch_rss(source)
        all_articles.extend(articles)
        time.sleep(config.DELAY_BETWEEN_SOURCES)
    return all_articles


# ── Веб-скрейпинг ────────────────────────────────────────────────────

def _scrape_kg_portal() -> list[Article]:
    """Скрейпинг KG-Portal (русскоязычные аниме-новости)."""
    url = "https://kg-portal.ru/news/anime/"
    logger.info("Scraping KG-Portal: %s", url)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articles = []
        # KG-Portal: список новостей в блоках .newsList .item или подобных
        for item in soup.select("a.newsListItem, .newsList .item a, .news-list-item a"):
            link = item.get("href", "")
            if link and not link.startswith("http"):
                link = "https://kg-portal.ru" + link

            title_el = item.select_one("h2, .title, .newsTitle")
            title = title_el.get_text(strip=True) if title_el else item.get_text(strip=True)

            img_el = item.select_one("img")
            image_url = img_el.get("src") if img_el else None
            if image_url and not image_url.startswith("http"):
                image_url = "https://kg-portal.ru" + image_url

            if not link or not title:
                continue

            articles.append(Article(
                url=link,
                title=title[:200],
                summary="",
                source="KG-Portal",
                language="ru",
                image_url=image_url,
            ))

        # Fallback: если селекторы не сработали, ищем все ссылки на /news/
        if not articles:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "/news/" in href and href != "/news/anime/" and a_tag.get_text(strip=True):
                    full_url = href if href.startswith("http") else "https://kg-portal.ru" + href
                    articles.append(Article(
                        url=full_url,
                        title=a_tag.get_text(strip=True)[:200],
                        summary="",
                        source="KG-Portal",
                        language="ru",
                        image_url=None,
                    ))

        # Убираем дубликаты по URL
        seen_urls: set[str] = set()
        unique: list[Article] = []
        for a in articles[:20]:
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                unique.append(a)
        articles = unique

        logger.info("  KG-Portal: получено %d статей", len(articles))
        return articles

    except Exception as e:
        logger.error("Ошибка при скрейпинге KG-Portal: %s", e)
        return []


def _scrape_crunchyroll() -> list[Article]:
    """Скрейпинг Crunchyroll News."""
    url = "https://www.crunchyroll.com/news"
    logger.info("Scraping Crunchyroll: %s", url)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articles = []
        # Crunchyroll news cards
        for card in soup.select(
            "a[href*='/news/'], .news-card a, article a, "
            "[class*='news'] a, [class*='card'] a"
        ):
            href = card.get("href", "")
            if not href or "/news" not in href:
                continue
            if href.startswith("/"):
                href = "https://www.crunchyroll.com" + href

            title_el = card.select_one("h3, h4, .title, span")
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)

            img_el = card.select_one("img")
            image_url = img_el.get("src") if img_el else None
            # Иногда в src лежит плейсхолдер, а реальная картинка в data-src (ленивая загрузка)
            if img_el and img_el.get("data-src"):
                image_url = img_el.get("data-src")
            # Или srcset, берём первую урлу
            elif img_el and img_el.get("srcset"):
                # "url1 1x, url2 2x" -> берем первую url1
                first_src = img_el.get("srcset").split(",")[0].split()[0]
                if first_src.startswith("http"):
                     image_url = first_src

            if not title or len(title) < 10:
                continue

            articles.append(Article(
                url=href,
                title=title[:200],
                summary="",
                source="Crunchyroll",
                language="en",
                image_url=image_url,
            ))

        # Дедупликация
        seen_urls: set[str] = set()
        unique: list[Article] = []
        for a in articles[:20]:
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                unique.append(a)
        articles = unique

        logger.info("  Crunchyroll: получено %d статей", len(articles))
        return articles

    except Exception as e:
        logger.error("Ошибка при скрейпинге Crunchyroll: %s", e)
        return []


def fetch_all_web() -> list[Article]:
    """Получить статьи из всех веб-источников."""
    scrapers = {
        "KG-Portal": _scrape_kg_portal,
        "Crunchyroll": _scrape_crunchyroll,
    }
    all_articles: list[Article] = []
    for name, scraper in scrapers.items():
        articles = scraper()
        all_articles.extend(articles)
        time.sleep(config.DELAY_BETWEEN_SOURCES)
    return all_articles


# ── Расписание аниме (YummyAnime) ─────────────────────────────────────

_DAYS_RU = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}


@dataclass
class ScheduleEntry:
    """Запись расписания: аниме, выходящее сегодня."""
    title: str
    anime_type: Optional[str] = None
    episode: Optional[int] = None
    rating: Optional[str] = None
    url: Optional[str] = None


def fetch_today_schedule() -> list[ScheduleEntry]:
    """Получить расписание аниме на сегодня с YummyAnime."""
    logger.info("Fetching today's schedule from YummyAnime")
    try:
        resp = requests.get(
            config.SCHEDULE_URL,
            headers=HEADERS,
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Определяем сегодняшний день недели на русском
        today_weekday = date.today().weekday()  # 0=Пн, 6=Вс
        today_name = _DAYS_RU[today_weekday]

        # Ищем заголовок сегодняшнего дня среди accordion-item
        day_headers = soup.select(".accordion-item")
        target_header = None
        for header in day_headers:
            header_text = header.get_text(strip=True)
            # На странице сегодняшний день может быть "Пятница (сегодня)" или просто "Пятница"
            if today_name in header_text or "сегодня" in header_text.lower():
                target_header = header
                break

        if target_header is None:
            logger.warning("Не найден заголовок для '%s' на странице YummyAnime", today_name)
            return []

        # Содержимое аккордеона — следующий sibling-div
        content = target_header.find_next_sibling()
        if content is None:
            logger.warning("Нет содержимого для '%s'", today_name)
            return []

        items = content.select(".anime-column.schedule")
        if not items:
            # Fallback: попробуем найти любые элементы с data-anime-id
            items = content.select("[data-anime-id]")

        entries: list[ScheduleEntry] = []
        for item in items:
            # Название
            title_el = item.select_one(".anime-title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title:
                continue

            # Ссылка
            href = title_el.get("href", "")
            full_url = f"https://site.yummyani.me{href}" if href and not href.startswith("http") else href

            # Тип (Сериал, ONA, Фильм...)
            type_el = item.select_one(".anime-column-info > div:nth-child(2)")
            anime_type = type_el.get_text(strip=True) if type_el else None

            # Рейтинг
            rating_el = item.select_one(".main-rating")
            rating = rating_el.get_text(strip=True) if rating_el else None

            entries.append(ScheduleEntry(
                title=title,
                anime_type=anime_type,
                episode=None,  # YummyAnime не показывает номер серии
                rating=rating,
                url=full_url or None,
            ))

        logger.info("  YummyAnime schedule: получено %d записей на %s", len(entries), today_name)
        return entries

    except Exception as e:
        logger.error("Ошибка при получении расписания YummyAnime: %s", e)
        return []


# ── Топ текущих эпизодов (AniList GraphQL) ────────────────────────────

@dataclass
class TopEpisodeEntry:
    """Эпизод для еженедельного баннера."""
    title: str
    episode_info: str       # e.g., "Эпизод 21"
    rating: float           # 0.0–10.0
    genres: list[str]
    cover_image_url: Optional[str] = None   # портретная обложка (~460×650)
    banner_image_url: Optional[str] = None  # широкий промо-баннер (~1900×400), приоритетный


_ANILIST_URL = "https://graphql.anilist.co"
_ANILIST_QUERY = """
query ($perPage: Int) {
  Page(perPage: $perPage) {
    media(
      status: RELEASING
      type: ANIME
      sort: TRENDING_DESC
      isAdult: false
    ) {
      title { romaji english }
      bannerImage
      coverImage { extraLarge }
      genres
      averageScore
      nextAiringEpisode { episode }
    }
  }
}
"""


def fetch_top_episodes(limit: int = 6) -> list[TopEpisodeEntry]:
    """Получить топ текущих аниме через AniList GraphQL API."""
    logger.info("Fetching top episodes from AniList")
    try:
        resp = requests.post(
            _ANILIST_URL,
            json={"query": _ANILIST_QUERY, "variables": {"perPage": limit * 3}},
            timeout=15,
        )
        resp.raise_for_status()
        media_list = resp.json()["data"]["Page"]["media"]

        entries: list[TopEpisodeEntry] = []
        for m in media_list:
            score = m.get("averageScore")
            if not score:
                continue

            title = (m["title"].get("english") or m["title"]["romaji"]).strip()
            rating = round(score / 10, 1)
            genres: list[str] = [g for i, g in enumerate(m.get("genres") or []) if i < 3]
            cover = (m.get("coverImage") or {}).get("extraLarge")
            banner = m.get("bannerImage")  # широкий промо-баннер, None если нет

            next_ep = m.get("nextAiringEpisode")
            ep_num = (next_ep["episode"] - 1) if next_ep else None
            episode_info = f"Эпизод {ep_num}" if ep_num else "Текущий сезон"

            entries.append(TopEpisodeEntry(
                title=title,
                episode_info=episode_info,
                rating=rating,
                genres=genres,
                cover_image_url=cover,
                banner_image_url=banner,
            ))

            if len(entries) >= limit:
                break

        entries.sort(key=lambda e: e.rating, reverse=True)
        logger.info("  AniList: получено %d записей для баннера", len(entries))
        return entries

    except Exception as e:
        logger.error("Ошибка получения топ-эпизодов с AniList: %s", e)
        return []


# ── Общий фетчер ──────────────────────────────────────────────────────

def fetch_all_sources() -> list[Article]:
    """Получить статьи из всех источников (RSS + Web)."""
    logger.info("=== Начинаем цикл парсинга ===")
    rss_articles = fetch_all_rss()
    web_articles = fetch_all_web()
    total = rss_articles + web_articles
    logger.info("=== Цикл завершён: всего %d статей ===", len(total))
    return total


# ── Утилиты ───────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Убрать HTML-теги из строки."""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)
