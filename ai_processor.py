"""
AI-процессор: оценка интересности, перевод и форматирование постов.

Поддерживает несколько LLM-провайдеров через OpenAI-совместимый SDK:
- Google Gemini (бесплатно, рекомендуется)
- Groq (бесплатно, очень быстрый)
- OpenAI (платный, опционально)

Все провайдеры работают через библиотеку openai — меняется только
api_key, base_url и model.
"""

import logging
import time
from typing import Optional

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

import config

logger = logging.getLogger(__name__)

# Максимум повторов при ошибках API
MAX_RETRIES = 1
RETRY_BACKOFF = 2  # секунды, умножается на номер попытки


# ── Мультипровайдер ──────────────────────────────────────────────────

def _get_provider_config(provider: str) -> dict:
    """Получить api_key, base_url и model для провайдера."""
    providers = {
        "gemini": {
            "api_key": config.GEMINI_API_KEY,
            "base_url": config.GEMINI_BASE_URL,
            "model": config.GEMINI_MODEL,
        },
        "groq": {
            "api_key": config.GROQ_API_KEY,
            "base_url": config.GROQ_BASE_URL,
            "model": config.GROQ_MODEL,
        },
        "openai": {
            "api_key": config.OPENAI_API_KEY,
            "base_url": config.OPENAI_BASE_URL,
            "model": config.OPENAI_MODEL,
        },
    }
    return providers.get(provider, providers["gemini"])


def _get_fallback_order() -> list[str]:
    """Порядок провайдеров: основной + фоллбэки (только с заполненным ключом)."""
    primary = config.LLM_PROVIDER
    order = [primary]
    for p in config.FALLBACK_PROVIDERS:
        if p != primary and p not in order:
            order.append(p)
    # Оставляем только те, у которых есть API-ключ
    return [p for p in order if _get_provider_config(p)["api_key"]]


def _create_client(provider: str) -> OpenAI:
    """Создать OpenAI-совместимый клиент для провайдера."""
    cfg = _get_provider_config(provider)
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])


# ── Основной вызов LLM ──────────────────────────────────────────────

def _call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1024,
) -> Optional[str]:
    """
    Вызов LLM с фоллбэком между провайдерами.

    Логика:
    1. Берём основной провайдер, пробуем MAX_RETRIES раз
    2. Если все попытки провалились (rate limit, ошибка) — переходим
       к следующему провайдеру из FALLBACK_PROVIDERS
    3. Повторяем до исчерпания всех провайдеров
    """
    providers = _get_fallback_order()

    if not providers:
        logger.error("Нет настроенных LLM-провайдеров! Заполните API-ключ в config.py")
        return None

    for provider in providers:
        cfg = _get_provider_config(provider)
        client = _create_client(provider)
        model = cfg["model"]

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                messages: list[ChatCompletionMessageParam] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.7,
                )
                result = response.choices[0].message.content
                if attempt > 1 or provider != providers[0]:
                    logger.info(
                        "Успешный ответ от %s/%s (попытка %d)",
                        provider, model, attempt,
                    )
                return result

            except Exception as e:
                error_str = str(e).lower()
                is_rate_limit = "429" in error_str or "rate" in error_str or "quota" in error_str

                logger.warning(
                    "LLM ошибка [%s/%s] (попытка %d/%d): %s",
                    provider, model, attempt, MAX_RETRIES, e,
                )

                # При rate limit сразу переключаемся на следующий провайдер
                if is_rate_limit:
                    logger.info("Rate limit у %s, переключаемся на следующий провайдер", provider)
                    break

                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF * attempt)

        logger.warning("Провайдер %s исчерпан, пробуем следующий...", provider)

    logger.error("Все LLM-провайдеры недоступны")
    return None


# ── Оценка интересности ──────────────────────────────────────────────

SCORING_SYSTEM_PROMPT = """Ты — редактор аниме-новостей. Проанализируй новость и верни ТОЛЬКО одну строку компактного JSON без переносов и отступов:
{"anime_names":["название"],"authors":["имя"],"is_teaser":false,"is_announcement":false,"is_trailer":false,"subjective_score":3}

КРИТЕРИИ:
- anime_names: все названия аниме/манги (не более 3, только самые важные).
- authors: имена авторов, режиссёров (не более 2).
- is_teaser/is_announcement/is_trailer: true если новость содержит это.
- subjective_score: 1-5 (5=критически важно, 1=проходняк).

Новость для анализа:
"""


def score_interest(title: str, summary: str, source: str) -> int:
    """
    Оценить интересность новости по бальной системе.
    Логика:
    1. ИИ извлекает сущности (аниме, авторы) и тип новости.
    2. Мы проверяем их по спискам популярных из config.py.
    3. Суммируем баллы из config.SCORING_WEIGHTS.
    """
    import json
    import re

    user_prompt = f"Источник: {source}\nЗаголовок: {title}\nОписание: {summary}"

    raw_result = _call_llm(
        system_prompt=SCORING_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=600,
    )

    if not raw_result:
        return 0

    try:
        # Убираем markdown-обёртку, затем ищем JSON-объект
        clean = re.sub(r"```json\s*|```", "", raw_result).strip()
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if not match:
            logger.warning("JSON не найден в ответе ИИ: %s", str(raw_result)[:80])
            return 0
        data = json.loads(match.group())

        final_score = 0
        breakdown = []

        # 1. Популярные аниме (+3 за каждое уникальное совпадение, макс 6)
        anime_found = data.get("anime_names", [])
        added_anime_points = 0
        for anime in anime_found:
            is_popular = any(
                p.lower() in anime.lower() or anime.lower() in p.lower()
                for p in config.POPULAR_ANIME
            )
            if is_popular:
                added_anime_points += config.SCORING_WEIGHTS["popular_anime"]
                if added_anime_points >= 6:
                    added_anime_points = 6
                    break
        if added_anime_points:
            final_score += added_anime_points
            breakdown.append(f"Anime: +{added_anime_points}")

        # 2. Популярные авторы (+2)
        authors_found = data.get("authors", [])
        author_points = 0
        for author in authors_found:
            is_popular = any(
                p.lower() in author.lower() or author.lower() in p.lower()
                for p in config.POPULAR_AUTHORS
            )
            if is_popular:
                author_points = config.SCORING_WEIGHTS["popular_author"]
                break
        if author_points:
            final_score += author_points
            breakdown.append(f"Author: +{author_points}")

        # 3. Тизеры / Анонсы / Трейлеры (+2)
        if data.get("is_teaser") or data.get("is_announcement") or data.get("is_trailer"):
            points = config.SCORING_WEIGHTS["teaser_announcement"]
            final_score += points
            breakdown.append(f"Format: +{points}")

        # 4. Субъективная оценка ИИ (1-5)
        subjective = data.get("subjective_score", 0)
        try:
            subjective = int(subjective)
        except (ValueError, TypeError):
            subjective = 2
        subjective = max(1, min(5, subjective))
        final_score += subjective
        breakdown.append(f"AI: +{subjective}")

        # 5. Бонус за надежный источник (опционально)
        if source in ["KG-Portal", "ANN", "MyAnimeList"]:
            points = config.SCORING_WEIGHTS.get("official_source", 1)
            final_score += points
            breakdown.append(f"Source: +{points}")

        logger.info(
            "Scoring [%s]: %d баллов (%s)",
            title[:50], final_score, ", ".join(breakdown)
        )

        # Ограничиваем 10 баллами для совместимости
        return min(10, final_score)

    except Exception as e:
        logger.warning("Ошибка при расчете score: %s. Ответ ИИ: %r", e, raw_result)
        return 0


# ── Перевод и форматирование поста ────────────────────────────────────

TRANSLATION_SYSTEM_PROMPT = f"""Ты — автор постов для Telegram-канала «{config.CHANNEL_NAME}» об аниме. Твоя задача — написать пост на основе сырой информации.

ГЛАВНОЕ ПРАВИЛО:
Оцени объем новости. Если это простой анонс, дата выхода или мелкий факт — пиши МАКСИМАЛЬНО КОРОТКО (1-2 абзаца) и добавляй интерактив (опрос через эмодзи). Если новость большая (скандал, подробный разбор, много деталей) — распиши на 3-4 абзаца, но без воды.

СТИЛЬ ПОСТОВ:
- Начни с одного эмодзи (👀🔥📺🎬⚔️🎌💀😱) и короткого цепляющего заголовка.
- Названия аниме/манги оборачивай в «кавычки-ёлочки».
- Пиши живо, неформально, как в чате с друзьями-анимешниками.
- Избегай тавтологии: никогда не повторяй одну и ту же мысль разными словами.
- Если новость КОРОТКАЯ, обязательно завершай её интерактивом с двумя эмодзи на выбор для подписчиков (пример: 🤬 – бесит / ❤️ – топ).

ЗАПРЕЩЁННЫЕ ФРАЗЫ И ШТАМПЫ (никогда не используй):
- «обещает быть интересным», «будет интересно посмотреть»
- «подробности не разглашаются», «детали пока неизвестны»
- «поклонники с нетерпением ждут», «сюжет рассказывает о...»
- «официально объявлено, что...»

ОБЯЗАТЕЛЬНО заверши пост строкой (с пустой строкой перед ней):
{config.POST_SIGNATURE}

ПРИМЕРЫ:
---
[Пример короткой новости с интерактивом]
🔥 Третий сезон аниме «Звёздное дитя» завершится 25 марта

🤔 Создатели подготовили часовой спецвыпуск, который поставит точку в сезоне.

🤬 – час это слишком
❤️ – киношка на вечер

{config.POST_SIGNATURE}
---
[Пример короткой новости с интерактивом]
👀 Синъитиро Ватанабэ приедет на Animazement

Создатель культового «Ковбой Бибоп» станет звездным гостем грядущей конвенции. Ждём жирных тизеров или инсайдов с панели!

🔥 – жду анонсов
🥱 – всё равно

{config.POST_SIGNATURE}
---
[Пример подробной новости]
📺 Мангу «Из другого мира» адаптируют в аниме-сериал

Студия анонсировала экранизацию на 2026 год. Режиссёром проекта выступит Норияки Абэ, который сделал себе имя на работе над «Bleach».

Это классический исекай, где главный герой проваливается в фэнтези с магией. Фишка в том, что ему придется буквально выживать, подстраиваясь под жесткие законы нового мира.

Если любите мрачные тайтлы без имбовых героев со старта — стоит взять на карандаш.

{config.POST_SIGNATURE}
---

Напиши ТОЛЬКО текст поста, без дополнительных комментариев, приветствий или хэштегов."""


def translate_and_format(
    title: str,
    summary: str,
    source_url: str,
    source_language: str,
) -> Optional[str]:
    """Перевести и отформатировать новость в готовый пост."""
    user_prompt = (
        f"Язык источника: {source_language}\n"
        f"Заголовок: {title}\n"
        f"Описание: {summary}\n"
        f"Ссылка: {source_url}"
    )

    result = _call_llm(
        system_prompt=TRANSLATION_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=800,
    )

    if result is None:
        return None

    post = result.strip()

    # Гарантируем подпись в конце
    if config.POST_SIGNATURE not in post:
        post = post.rstrip() + "\n\n" + config.POST_SIGNATURE

    return post


# ── Генерация поста с расписанием ─────────────────────────────────────

SCHEDULE_SYSTEM_PROMPT = f"""Ты — автор постов для Telegram-канала «{config.CHANNEL_NAME}». Сгенерируй пост с расписанием аниме на сегодня.

Формат:
📺 Аниме, которые выходят сегодня:

• «Название»
• «Название» (⭐ 8.5)
(и так далее)

ПРАВИЛА:
- Названия уже на русском, НЕ переводи их и не меняй
- Оборачивай названия в «кавычки»
- Если указан рейтинг и он ≥ 7.0, добавь ⭐ с оценкой
- Пропускай фильмы (тип "Фильм" или "Полнометражный фильм") — нам важны только сериалы/ONA
- Можно добавить короткую подводку (одна строка) после заголовка

В конце обязательно:
{config.POST_SIGNATURE}

Напиши ТОЛЬКО пост."""


def generate_schedule_post(anime_list: list[dict]) -> Optional[str]:
    """Сгенерировать пост с расписанием выходящих сегодня аниме.

    anime_list: [{"title": "...", "anime_type": "...", "rating": "...", "episode": N или None}, ...]
    """
    if not anime_list:
        return None

    entries = []
    for a in anime_list:
        title = a.get("title", "Unknown")
        anime_type = a.get("anime_type", "")
        rating = a.get("rating", "")
        parts = [f"- {title}"]
        if anime_type:
            parts.append(f"(тип: {anime_type})")
        if rating:
            parts.append(f"[рейтинг: {rating}]")
        entries.append(" ".join(parts))

    user_prompt = "Вот список аниме на сегодня:\n" + "\n".join(entries)

    result = _call_llm(
        system_prompt=SCHEDULE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=600,
    )

    if result is None:
        return None

    post = result.strip()
    if config.POST_SIGNATURE not in post:
        post = post.rstrip() + "\n\n" + config.POST_SIGNATURE

    return post