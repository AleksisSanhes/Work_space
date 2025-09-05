# bot/telegram_bot.py
import hashlib
import logging
from bot.database import SafeNewsDB

logger = logging.getLogger(__name__)

# --- Константы каналов (переместить в config позже) ---
MODERATION_CHANNEL = "-1002996332660"
PUBLISH_CHANNEL = "-1003006895565"


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


async def send_to_moderation(bot, news_item: dict, db: SafeNewsDB):
    """
    Отправка новости в канал модерации с кнопками approve/reject/edit.
    DEPRECATED: Используйте TelegramService.send_to_moderation()
    """
    logger.warning("Using deprecated send_to_moderation function. Use TelegramService instead.")

    # Для временной совместимости - можно будет удалить после рефакторинга
    from config import TelegramConfig
    from bot.services.telegram_service import TelegramService

    config = TelegramConfig(
        moderation_channel=MODERATION_CHANNEL,
        publish_channel=PUBLISH_CHANNEL
    )
    telegram_service = TelegramService(config)

    news_id = news_item["id"]
    message = await telegram_service.send_to_moderation(bot, news_item, news_id)

    if message and message.message_id:
        db.add_news(news_id, news_item, message.message_id, MODERATION_CHANNEL)
        logger.info(f"Новость {news_id} отправлена в модерацию (message_id={message.message_id})")
    else:
        logger.error(f"Не удалось отправить новость {news_id} в канал модерации")