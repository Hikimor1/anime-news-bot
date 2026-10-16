"""
Генератор баннеров: HTML-шаблон (Jinja2) + Playwright скриншот.
Создаёт 2 PNG-файла (по 3 карточки) для еженедельного поста топ-6 эпизодов.
"""

import base64
import itertools
import logging
import os
import tempfile
import requests
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

import config

logger = logging.getLogger(__name__)


def _get_current_season() -> str:
    month = datetime.now().month
    if month in (12, 1, 2):
        return "Зима"
    if month in (3, 4, 5):
        return "Весна"
    if month in (6, 7, 8):
        return "Лето"
    return "Осень"


@dataclass
class EpisodeData:
    rank: int
    title: str
    genres: List[str]
    episode_info: str  # e.g., "Сезон 3 Эпизод 21"
    rating: str
    image_url: Optional[str] = None
    local_image_path: Optional[str] = None


class ImageGenerator:
    def __init__(self, width: int = 1080):
        self.width = width
        self.card_height = 280
        self.padding = 40

        template_dir = Path(__file__).parent / "templates"
        self.jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
        self.template = self.jinja_env.get_template("banner.html")

    def _fetch_image_base64(self, url: str) -> Optional[str]:
        """Скачать изображение и вернуть как base64 data URI."""
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "image/jpeg")
            b64 = base64.b64encode(resp.content).decode("utf-8")
            return f"data:{ct};base64,{b64}"
        except Exception as e:
            logger.warning("Не удалось скачать обложку %s: %s", url, e)
            return None

    def _build_template_data(self, episodes: List[EpisodeData]) -> list:
        """Подготовить данные карточек для Jinja2-шаблона."""
        cards = []
        for ep in episodes:
            image_data = ""
            if ep.local_image_path and os.path.exists(str(ep.local_image_path)):
                with open(ep.local_image_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    image_data = f"data:image/jpeg;base64,{b64}"
            elif ep.image_url:
                image_data = self._fetch_image_base64(str(ep.image_url)) or ""

            cards.append({
                "rank": ep.rank,
                "title": ep.title.upper(),
                "genres": ep.genres,
                "episode_info": ep.episode_info,
                "rating": ep.rating,
                "image_data": image_data,
            })
        return cards

    def generate_banner_pair(self, episodes: List[EpisodeData], output_dir: Optional[str] = None) -> List[str]:
        """Генерировать 2 баннера по 3 карточки. Возвращает список путей к PNG-файлам."""
        if output_dir is None:
            output_dir = tempfile.gettempdir()

        week = datetime.now().isocalendar()[1]
        season = _get_current_season()
        year = datetime.now().year
        subheader = f"Неделя {week}  \u2022  {season} {year}  \u2022  {config.CHANNEL_NAME}"

        batches = [
            list(itertools.islice(episodes, 0, 3)),
            list(itertools.islice(episodes, 3, 6)),
        ]

        paths: List[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for batch_index, batch in enumerate(batches):
                if not batch:
                    break

                for i, ep in enumerate(batch):
                    ep.rank = batch_index * 3 + i + 1

                cards = self._build_template_data(batch)
                html = self.template.render(
                    episodes=cards,
                    subheader=subheader,
                    width=self.width,
                    padding=self.padding,
                    card_height=self.card_height,
                )

                page = browser.new_page(viewport={"width": self.width, "height": 1})
                page.set_content(html, wait_until="networkidle")

                # Подгоняем высоту под содержимое
                height = page.evaluate("document.querySelector('.banner').offsetHeight")
                page.set_viewport_size({"width": self.width, "height": height})

                path = os.path.join(output_dir, f"weekly_banner_{batch_index + 1}.png")
                page.locator(".banner").screenshot(path=path)
                page.close()

                paths.append(path)
                logger.info("Баннер %d сохранён: %s", batch_index + 1, path)

            browser.close()

        return paths


if __name__ == "__main__":
    gen = ImageGenerator()
    test_data = [
        EpisodeData(1, "Fire Force", ["Экшен", "Фэнтези", "НФ"], "Сезон 3 Эпизод 21", "9.7"),
        EpisodeData(2, "Jujutsu Kaisen", ["Экшен", "Сверхъестественное"], "Сезон 3 Эпизод 9", "9.6"),
        EpisodeData(3, "Gnosia", ["НФ", "Саспенс", "Выживание"], "Эпизод 20", "9.6"),
    ]
    paths = gen.generate_banner_pair(test_data)
    print(f"Test banners: {paths}")
