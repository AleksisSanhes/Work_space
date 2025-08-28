# bot/telegram_bot.py
import asyncio
import hashlib
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter
from bot.formatters import format_news_for_publication
from bot.db import NewsDB

logger = logging.getLogger(__name__)

# --- Константы каналов ---
MODERATION_CHANNEL = "-1002996332660"
PUBLISH_CHANNEL = "-1003006895565"

# --- Утилиты ---
def make_news_id(item, index=0):
    """
    Генерирует уникальный ID новости на основе URL, заголовка или превью.
    """
    key = (item.get("url") or "").strip()
    if not key:
        key = f"{item.get('title','')}-{item.get('date','')}".strip()
    if not key:
        key = item.get("preview", "")[:120]
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


async def send_with_delay(bot: Bot, chat_id: str, text: str, reply_markup=None,
                          pause: float = 1.5, max_retries: int = 5):
    """
    Отправка сообщения с задержкой и повторной попыткой при ошибках.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(pause)
            return message
        except RetryAfter as e:
            wait_time = e.retry_after
            logger.warning(f"Flood control: ждём {wait_time} сек...")
            await asyncio.sleep(wait_time)
            attempt += 1
        except TelegramError as e:
            logger.error(f"Ошибка Telegram при отправке: {e}")
            return None
        except Exception as e:
            logger.error(f"Неизвестная ошибка при отправке: {e}")
            return None
    logger.error("Не удалось отправить сообщение после всех попыток.")
    return None


async def send_to_moderation(bot: Bot, news_item: dict, db: NewsDB):
    """
    Отправка новости в канал модерации с кнопками approve/reject/edit.
    """
    news_id = news_item["id"]
    text = (
        f"📰 <b>{news_item['title']}</b>\n\n"
        f"{news_item['preview']}\n\n"
        f"<i>Источник: {news_item['source']} ({news_item['date']})</i>\n"
        f"{news_item['url']}"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve|{news_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject|{news_id}"),
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit|{news_id}")
        ]
    ]

    logger.info(f"Отправка новости {news_id} в канал модерации...")
    message = await send_with_delay(
        bot,
        MODERATION_CHANNEL,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    if message:
        db.add_news(news_id, news_item, message.message_id, MODERATION_CHANNEL)
        logger.info(f"Новость {news_id} отправлена в модерацию (message_id={message.message_id})")
    else:
        logger.error(f"Не удалось отправить новость {news_id} в канал модерации.")
