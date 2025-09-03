import asyncio
import hashlib
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter
from bot.formatters import format_news_for_publication
from bot.database import SafeNewsDB

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
        key = f"{item.get('title', '')}-{item.get('date', '')}".strip()
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
                disable_web_page_preview=True
                # Убираем parse_mode='HTML' чтобы избежать ошибок парсинга
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


async def send_to_moderation(bot: Bot, news_item: dict, db: SafeNewsDB):
    """
    Отправка новости в канал модерации с кнопками approve/reject/edit.
    """
    news_id = news_item["id"]

    # Безопасная очистка текста от HTML и экранирование
    def clean_and_safe_text(text):
        if not text:
            return ""
        # Удаляем HTML теги
        import re
        text = re.sub(r'<[^>]+>', '', str(text))
        # Убираем лишние пробелы
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    title = clean_and_safe_text(news_item.get('title', 'Без заголовка'))
    preview = clean_and_safe_text(news_item.get('preview', ''))
    source = clean_and_safe_text(news_item.get('source', 'Источник не указан'))
    date = clean_and_safe_text(news_item.get('date', ''))
    url = news_item.get('url', '')

    text = (
        f"📰 {title}\n\n"
        f"{preview}\n\n"
        f"Источник: {source} ({date})\n"
        f"{url}"
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

    if message and message.message_id:
        # ИСПРАВЛЕНО: Проверяем, что message_id действительно получен
        db.add_news(news_id, news_item, message.message_id, MODERATION_CHANNEL)
        logger.info(f"Новость {news_id} отправлена в модерацию (message_id={message.message_id})")

        # Дополнительная проверка, что данные сохранились корректно
        saved_data = db.get_news(news_id)
        if saved_data and saved_data.get("message_id"):
            logger.info(f"Подтверждение: message_id {saved_data['message_id']} сохранен для новости {news_id}")
        else:
            logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: message_id не сохранился для новости {news_id}")
    else:
        logger.error(f"Не удалось отправить новость {news_id} в канал модерации или получить message_id.")