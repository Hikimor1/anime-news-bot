"""
Telegram-бот: отправка постов на ревью админу, публикация в канал,
обработка inline-кнопок и админских команд.

Использует python-telegram-bot v20+ (async).
"""

import logging
from typing import Optional

from telegram import (
    Bot,
    InputMediaPhoto,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import database as db

logger = logging.getLogger(__name__)

# Callback data prefixes
CB_APPROVE = "approve_"
CB_REJECT = "reject_"
CB_EDIT = "edit_"
CB_BANNER_APPROVE = "banner_approve_"
CB_BANNER_REJECT = "banner_reject_"

# Хранилище ID поста, ожидающего редактирования (per admin)
_edit_pending: dict[int, int] = {}  # admin_chat_id -> post_id

# Хранилище ожидающих баннеров: banner_id -> {paths, caption}
_pending_banners: dict[int, dict] = {}
_banner_counter: list[int] = [0]  # изменяемый счётчик (обход ограничений Pylance на global)


def _admin_only(func):
    """Декоратор: пропускает только сообщения от админа."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and update.effective_user.id != config.ADMIN_CHAT_ID:
            return
        return await func(update, context)
    return wrapper


# ── Отправка поста на ревью ───────────────────────────────────────────

async def send_for_review(bot: Bot, post_id: int, formatted_post: str, source: str, score: int, image_url: Optional[str] = None) -> bool:
    """Отправить пост админу на ревью с inline-кнопками."""
    review_header = f"📰 <b>Новый пост</b> | Источник: {source} | Оценка: {score}/10\n\n"
    full_text = review_header + formatted_post

    # Telegram message cap is 4096, but for captions it's 1024
    is_caption_too_long = len(full_text) > 1024

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"{CB_APPROVE}{post_id}"),
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"{CB_EDIT}{post_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"{CB_REJECT}{post_id}"),
        ]
    ])

    try:
        if image_url and not is_caption_too_long:
            msg = await bot.send_photo(
                chat_id=config.ADMIN_CHAT_ID,
                photo=image_url,
                caption=full_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            if image_url and is_caption_too_long:
                # Отправляем фото отдельным сообщением без клавиатуры и подписи (превью)
                try:
                    await bot.send_photo(chat_id=config.ADMIN_CHAT_ID, photo=image_url)
                except Exception as e_img:
                    logger.warning("Не удалось отправить фото отдельно: %s", e_img)

            msg = await bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=full_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
        
        db.update_post_status(post_id, "sent_for_review", tg_message_id=msg.message_id)
        logger.info("Пост #%d отправлен на ревью (msg_id=%d)", post_id, msg.message_id)
        return True
    except Exception as e:
        # Если HTML-парсинг не сработал или отправка фото упала, отправляем без форматирования
        logger.warning("Ошибка отправки (HTML/Photo), пробуем без HTML: %s", e)
        try:
            if image_url and not is_caption_too_long:
                msg = await bot.send_photo(
                    chat_id=config.ADMIN_CHAT_ID,
                    photo=image_url,
                    caption=f"📰 Новый пост | Источник: {source} | Оценка: {score}/10\n\n{formatted_post}",
                    reply_markup=keyboard,
                )
            else:
                msg = await bot.send_message(
                    chat_id=config.ADMIN_CHAT_ID,
                    text=f"📰 Новый пост | Источник: {source} | Оценка: {score}/10\n\n{formatted_post}",
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
            db.update_post_status(post_id, "sent_for_review", tg_message_id=msg.message_id)
            return True
        except Exception as e2:
            logger.error("Не удалось отправить пост #%d на ревью: %s", post_id, e2)
            return False


# ── Публикация в канал ────────────────────────────────────────────────

async def publish_to_channel(bot: Bot, text: str, image_url: Optional[str] = None) -> Optional[int]:
    """Опубликовать текст в канал. Возвращает message_id."""
    is_caption_too_long = len(text) > 1024

    try:
        if image_url and not is_caption_too_long:
            msg = await bot.send_photo(
                chat_id=config.CHANNEL_ID,
                photo=image_url,
                caption=text,
            )
        else:
            if image_url and is_caption_too_long:
                try:
                    await bot.send_photo(chat_id=config.CHANNEL_ID, photo=image_url)
                except Exception as e_img:
                    logger.warning("Не удалось отправить фото отдельно в канал: %s", e_img)

            msg = await bot.send_message(
                chat_id=config.CHANNEL_ID,
                text=text,
                disable_web_page_preview=True,
            )
        logger.info("Пост опубликован в канал (msg_id=%d)", msg.message_id)
        return msg.message_id
    except Exception as e:
        logger.error("Ошибка публикации в канал: %s", e)
        return None


# ── Баннерные функции ─────────────────────────────────────────────────

async def send_banner_for_review(bot: Bot, banner_paths: list, caption: str) -> bool:
    """Отправить баннеры (2 изображения) на ревью админу."""
    _banner_counter[0] += 1
    bid = _banner_counter[0]
    _pending_banners[bid] = {"paths": banner_paths, "caption": caption}

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"{CB_BANNER_APPROVE}{bid}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"{CB_BANNER_REJECT}{bid}"),
    ]])

    try:
        media = [InputMediaPhoto(media=open(p, "rb")) for p in banner_paths]
        await bot.send_media_group(chat_id=config.ADMIN_CHAT_ID, media=media)
        await bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=f"🏆 <b>Еженедельный баннер #{bid}</b>\n\n{caption}",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        logger.info("Баннер #%d отправлен на ревью", bid)
        return True
    except Exception as e:
        logger.error("Ошибка отправки баннера #%d: %s", bid, e)
        _pending_banners.pop(bid, None)
        return False


async def publish_banner_to_channel(bot: Bot, banner_paths: list, caption: str) -> bool:
    """Опубликовать 2 баннера в канал как media group."""
    try:
        media = [
            InputMediaPhoto(media=open(banner_paths[0], "rb")),
            InputMediaPhoto(media=open(banner_paths[1], "rb"), caption=caption),
        ]
        await bot.send_media_group(chat_id=config.CHANNEL_ID, media=media)
        logger.info("Баннер опубликован в канал")
        return True
    except Exception as e:
        logger.error("Ошибка публикации баннера в канал: %s", e)
        return False


# ── Обработчики callback-кнопок ───────────────────────────────────────

@_admin_only
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий на inline-кнопки."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""

    if data.startswith(CB_BANNER_APPROVE):
        await _handle_banner_approve(query, context)
    elif data.startswith(CB_BANNER_REJECT):
        await _handle_banner_reject(query, context)
    elif data.startswith(CB_APPROVE):
        await _handle_approve(query, context)
    elif data.startswith(CB_REJECT):
        await _handle_reject(query, context)
    elif data.startswith(CB_EDIT):
        await _handle_edit_request(query, context)


async def _handle_approve(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Одобрить и опубликовать пост."""
    post_id = int(query.data.replace(CB_APPROVE, ""))
    post = db.get_post_by_id(post_id)
    if not post:
        await query.edit_message_text("⚠️ Пост не найден в базе.")
        return

    # Проверяем лимит публикаций за день
    published_today = db.count_published_today()
    if published_today >= config.MAX_POSTS_PER_DAY:
        await query.edit_message_text(
            f"⚠️ Достигнут лимит публикаций на сегодня ({config.MAX_POSTS_PER_DAY}). "
            "Пост остаётся в очереди."
        )
        return

    # Публикуем
    msg_id = await publish_to_channel(context.bot, post["formatted_post"], post["image_url"])
    if msg_id:
        db.update_post_status(post_id, "published")
        await query.edit_message_text(
            f"✅ Пост #{post_id} опубликован в канал!"
        )
    else:
        await query.edit_message_text(
            f"⚠️ Ошибка при публикации поста #{post_id}. Попробуйте снова."
        )


async def _handle_reject(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отклонить пост."""
    post_id = int(query.data.replace(CB_REJECT, ""))
    db.update_post_status(post_id, "rejected")
    await query.edit_message_text(f"❌ Пост #{post_id} отклонён.")
    logger.info("Пост #%d отклонён", post_id)


async def _handle_edit_request(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запросить редактирование: ожидаем следующее сообщение от админа."""
    post_id = int(query.data.replace(CB_EDIT, ""))
    _edit_pending[config.ADMIN_CHAT_ID] = post_id
    await query.edit_message_text(
        f"✏️ Пост #{post_id}: отправьте исправленный текст поста следующим сообщением."
    )


async def _handle_banner_approve(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Одобрить и опубликовать еженедельный баннер."""
    bid = int(query.data.replace(CB_BANNER_APPROVE, ""))
    banner = _pending_banners.pop(bid, None)
    if not banner:
        await query.edit_message_text("⚠️ Баннер не найден (уже опубликован или отклонён).")
        return

    ok = await publish_banner_to_channel(context.bot, banner["paths"], banner["caption"])
    if ok:
        await query.edit_message_text(f"✅ Баннер #{bid} опубликован в канал!")
    else:
        await query.edit_message_text(f"⚠️ Ошибка публикации баннера #{bid}.")


async def _handle_banner_reject(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отклонить еженедельный баннер."""
    bid = int(query.data.replace(CB_BANNER_REJECT, ""))
    _pending_banners.pop(bid, None)
    await query.edit_message_text(f"❌ Баннер #{bid} отклонён.")
    logger.info("Баннер #%d отклонён", bid)


# ── Обработка текстовых сообщений (редактирование) ────────────────────

@_admin_only
async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Принять отредактированный текст от админа."""
    admin_id = config.ADMIN_CHAT_ID
    if admin_id not in _edit_pending:
        return  # нет ожидающего редактирования

    post_id = _edit_pending.pop(admin_id)
    new_text = update.message.text if update.message else None
    if not new_text:
        return

    # Обновляем текст и отправляем заново на ревью
    db.update_post_status(post_id, "pending", formatted_post=new_text)

    post = db.get_post_by_id(post_id)
    if post:
        await send_for_review(
            context.bot, post_id, new_text,
            post["source"], post["interest_score"], post["image_url"],
        )
        await update.message.reply_text(f"✏️ Пост #{post_id} обновлён и отправлен заново на ревью.")


# ── Команды админа ────────────────────────────────────────────────────

@_admin_only
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/pending — показать количество постов в очереди."""
    stats = db.get_today_stats()
    await update.message.reply_text(
        f"📋 В очереди: {stats['pending']} постов\n"
        f"📤 Опубликовано сегодня: {stats['published']}\n"
        f"❌ Отклонено сегодня: {stats['rejected']}"
    )


@_admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — статистика за сегодня."""
    stats = db.get_today_stats()
    await update.message.reply_text(
        f"📊 Статистика за сегодня:\n\n"
        f"📥 Получено статей: {stats['fetched']}\n"
        f"📤 Опубликовано: {stats['published']}\n"
        f"❌ Отклонено: {stats['rejected']}\n"
        f"📋 В очереди: {stats['pending']}"
    )


@_admin_only
async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fetch — принудительный запуск цикла парсинга."""
    await update.message.reply_text("🔄 Запускаю цикл парсинга...")
    # Импортируем здесь, чтобы избежать циклического импорта
    from scheduler import run_fetch_cycle
    await run_fetch_cycle(context.bot)
    await update.message.reply_text("✅ Цикл парсинга завершён.")


@_admin_only
async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/schedule — сгенерировать и отправить расписание."""
    await update.message.reply_text("📺 Генерирую расписание...")
    from scheduler import run_schedule_post
    await run_schedule_post(context.bot)
    await update.message.reply_text("✅ Расписание обработано.")


@_admin_only
async def cmd_banner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/banner — вручную сгенерировать еженедельный баннер."""
    await update.message.reply_text("🏆 Генерирую еженедельный баннер...")
    from scheduler import run_weekly_banner
    await run_weekly_banner(context.bot)
    await update.message.reply_text("✅ Баннер обработан.")


@_admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — приветствие."""
    await update.message.reply_text(
        f"🤖 Anime News Bot для канала {config.CHANNEL_NAME}\n\n"
        "Команды:\n"
        "/pending — посты в очереди\n"
        "/stats — статистика за сегодня\n"
        "/fetch — запустить парсинг\n"
        "/schedule — расписание на сегодня\n"
        "/banner — еженедельный баннер топ-6"
    )


# ── Создание Application ─────────────────────────────────────────────

def create_application(post_init=None) -> Application:
    """Создать и настроить Telegram Application."""
    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    if post_init is not None:
        builder = builder.post_init(post_init)
    app = builder.build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("fetch", cmd_fetch))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("banner", cmd_banner))

    # Inline-кнопки
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Текстовые сообщения (для редактирования постов)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(config.ADMIN_CHAT_ID),
        handle_edit_text,
    ))

    return app
