# bot/services/telegram_service.py
import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from enum import Enum
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError

from bot.formatters import format_news_for_publication
from config import TelegramConfig

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerStats:
    failure_count: int = 0
    last_failure_time: float = 0
    success_count: int = 0
    total_requests: int = 0
    state_changes: List[tuple] = field(default_factory=list)


class CircuitBreaker:
    """Circuit breaker for handling service failures gracefully."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0,
                 expected_exception: type = TelegramError):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.state = CircuitBreakerState.CLOSED
        self.stats = CircuitBreakerStats()

    def _change_state(self, new_state: CircuitBreakerState, reason: str = ""):
        old_state = self.state
        self.state = new_state
        timestamp = time.time()
        self.stats.state_changes.append((timestamp, old_state.value, new_state.value, reason))
        logger.info(f"Circuit breaker state changed: {old_state.value} -> {new_state.value} ({reason})")

    def _should_attempt_reset(self) -> bool:
        return (
                self.state == CircuitBreakerState.OPEN and
                time.time() - self.stats.last_failure_time > self.recovery_timeout
        )

    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        self.stats.total_requests += 1

        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                self._change_state(CircuitBreakerState.HALF_OPEN, "recovery timeout reached")
            else:
                raise TelegramError("Circuit breaker is OPEN")

        try:
            result = await func(*args, **kwargs)

            # Success
            if self.state == CircuitBreakerState.HALF_OPEN:
                self._change_state(CircuitBreakerState.CLOSED, "successful call in half-open state")
                self.stats.failure_count = 0

            self.stats.success_count += 1
            return result

        except self.expected_exception as e:
            self.stats.failure_count += 1
            self.stats.last_failure_time = time.time()

            if (self.state == CircuitBreakerState.CLOSED and
                    self.stats.failure_count >= self.failure_threshold):
                self._change_state(CircuitBreakerState.OPEN, f"failure threshold reached ({self.stats.failure_count})")
            elif self.state == CircuitBreakerState.HALF_OPEN:
                self._change_state(CircuitBreakerState.OPEN, "failure in half-open state")

            raise


class TelegramService:
    """Enhanced Telegram service with reliability features."""

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.circuit_breaker = CircuitBreaker()
        self._message_cache: Dict[str, int] = {}  # Cache for deduplication

    def make_news_id(self, item: dict, index: int = 0) -> str:
        """Generate unique ID for news item."""
        key = (item.get("url") or "").strip()
        if not key:
            key = f"{item.get('title', '')}-{item.get('date', '')}".strip()
        if not key:
            key = item.get("preview", "")[:120]

        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    async def send_with_retry(self, bot: Bot, chat_id: str, text: str,
                              reply_markup: Optional[InlineKeyboardMarkup] = None,
                              **kwargs) -> Optional[Message]:
        """Send message with exponential backoff retry logic."""

        logger.info(f"TELEGRAM_SERVICE: Attempting to send message to chat_id={chat_id}")
        logger.info(f"TELEGRAM_SERVICE: Message text preview: {text[:100]}...")

        # Check for duplicate messages
        message_hash = hashlib.md5(f"{chat_id}:{text}".encode()).hexdigest()
        if message_hash in self._message_cache:
            recent_time = time.time() - self._message_cache[message_hash]
            if recent_time < 60:  # Prevent duplicates within 1 minute
                logger.warning(f"Duplicate message detected, skipping: {text[:50]}...")
                return None

        async def _send():
            logger.info(f"TELEGRAM_SERVICE: Executing bot.send_message to {chat_id}")
            result = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                **kwargs
            )
            logger.info(f"TELEGRAM_SERVICE: Successfully sent message to {chat_id}, message_id={result.message_id}")
            return result

        for attempt in range(self.config.retry_attempts):
            try:
                message = await self.circuit_breaker.call(_send)

                if message:
                    self._message_cache[message_hash] = time.time()
                    # Clean old cache entries
                    if len(self._message_cache) > 1000:
                        current_time = time.time()
                        self._message_cache = {
                            k: v for k, v in self._message_cache.items()
                            if current_time - v < 3600  # Keep only last hour
                        }

                await asyncio.sleep(self.config.flood_control_delay)
                return message

            except RetryAfter as e:
                wait_time = e.retry_after + 1
                logger.warning(f"Rate limited, waiting {wait_time} seconds...")
                await asyncio.sleep(wait_time)

            except (TimedOut, NetworkError) as e:
                wait_time = min(2 ** attempt, 60)  # Exponential backoff, max 60s
                logger.warning(f"Network error on attempt {attempt + 1}: {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

            except TelegramError as e:
                logger.error(f"TELEGRAM_SERVICE ERROR: Telegram error on attempt {attempt + 1} (chat_id: {chat_id}): {e}")
                logger.error(f"TELEGRAM_SERVICE ERROR: Message text (first 200 chars): {text[:200]}")
                if "Bad Request" in str(e):  # Don't retry bad requests
                    logger.error(f"TELEGRAM_SERVICE ERROR: Bad Request details: {e}")
                    logger.error(f"TELEGRAM_SERVICE ERROR: This is the request causing Bad Request!")
                    break
                await asyncio.sleep(2 ** attempt)

            except Exception as e:
                logger.error(f"TELEGRAM_SERVICE ERROR: Unexpected error on attempt {attempt + 1} (chat_id: {chat_id}): {e}")
                logger.error(f"TELEGRAM_SERVICE ERROR: Message text (first 200 chars): {text[:200]}")
                await asyncio.sleep(2 ** attempt)

        logger.error(f"TELEGRAM_SERVICE: Failed to send message after {self.config.retry_attempts} attempts to chat_id: {chat_id}")
        return None

    async def split_and_send_message(self, bot: Bot, chat_id: str, text: str,
                                     max_length: int = None) -> List[int]:
        """Split long text and send as multiple messages."""
        if max_length is None:
            max_length = self.config.max_message_length

        message_ids = []

        if len(text) <= max_length:
            message = await self.send_with_retry(bot, chat_id, text)
            if message:
                message_ids.append(message.message_id)
            return message_ids

        # Smart splitting by sentences
        sentences = text.split('. ')
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk + sentence + '. ') <= max_length:
                current_chunk += sentence + '. '
            else:
                if current_chunk:
                    message = await self.send_with_retry(bot, chat_id, current_chunk.strip())
                    if message:
                        message_ids.append(message.message_id)
                    current_chunk = sentence + '. '
                else:
                    # Handle very long sentences
                    while len(sentence) > max_length:
                        chunk = sentence[:max_length]
                        message = await self.send_with_retry(bot, chat_id, chunk)
                        if message:
                            message_ids.append(message.message_id)
                        sentence = sentence[max_length:]
                    current_chunk = sentence + '. ' if sentence else ""

        # Send remaining text
        if current_chunk:
            message = await self.send_with_retry(bot, chat_id, current_chunk.strip())
            if message:
                message_ids.append(message.message_id)

        return message_ids

    async def safe_delete_messages(self, bot: Bot, chat_id: str,
                                   message_ids: List[int], news_id: str = "") -> int:
        """Safely delete multiple messages."""
        if not message_ids:
            logger.debug(f"No message IDs provided for deletion (news: {news_id})")
            return 0

        deleted_count = 0
        for message_id in message_ids:
            if message_id is None:
                logger.debug(f"Skipping None message_id for news {news_id}")
                continue

            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                deleted_count += 1
                await asyncio.sleep(0.1)  # Small delay between deletions
                logger.debug(f"Successfully deleted message {message_id} for news {news_id}")

            except TelegramError as e:
                # Check if it's a "message to delete not found" error
                if "message to delete not found" in str(e).lower() or "message can't be deleted" in str(e).lower():
                    logger.debug(f"Message {message_id} already deleted or not found for news {news_id}")
                else:
                    logger.warning(f"Failed to delete message {message_id} for news {news_id}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error deleting message {message_id} for news {news_id}: {e}")

        logger.info(f"Deleted {deleted_count}/{len(message_ids)} messages for news {news_id}")
        return deleted_count

    def create_moderation_keyboard(self, news_id: str) -> InlineKeyboardMarkup:
        """Create keyboard for news moderation."""
        keyboard = [
            [
                InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve|{news_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject|{news_id}"),
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit|{news_id}")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def safe_escape_text(self, text: str) -> str:
        """Safely escape text for Telegram."""
        if not text:
            return ""

        # Remove HTML tags
        import re
        text = re.sub(r'<[^>]+>', '', str(text))

        # Clean multiple whitespaces
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def format_moderation_message(self, news_item: dict, news_id: str, edited: bool = False) -> str:
        """Format news item for moderation channel."""
        title = self.safe_escape_text(news_item.get("title", "Без заголовка"))
        preview = self.safe_escape_text(news_item.get("preview", ""))
        source = self.safe_escape_text(news_item.get("source", "Источник не указан"))
        date = self.safe_escape_text(news_item.get("date", ""))
        url = news_item.get("url", "")

        edit_marker = " ✏️ ОТРЕДАКТИРОВАНО" if edited else ""

        return (
            f"📰 {title}{edit_marker}\n\n"
            f"{preview}\n\n"
            f"Источник: {source} ({date})\n"
            f"{url}"
        )

    async def send_to_moderation(self, bot: Bot, news_item: dict, news_id: str) -> Optional[Message]:
        """Send news to moderation channel."""
        try:
            text = self.format_moderation_message(news_item, news_id)
            keyboard = self.create_moderation_keyboard(news_id)

            message = await self.send_with_retry(
                bot,
                self.config.moderation_channel,
                text,
                reply_markup=keyboard
            )

            if message:
                logger.info(f"News {news_id} sent to moderation (message_id={message.message_id})")
            else:
                logger.error(f"Failed to send news {news_id} to moderation")

            return message

        except Exception as e:
            logger.error(f"Error sending news {news_id} to moderation: {e}")
            return None

    async def publish_news(self, bot: Bot, news_item: dict, news_id: str) -> bool:
        """Publish news to the main channel."""
        try:
            publication_text = format_news_for_publication(news_item)

            message = await self.send_with_retry(
                bot,
                self.config.publish_channel,
                publication_text
            )

            if message:
                logger.info(f"News {news_id} published successfully")
                return True
            else:
                logger.error(f"Failed to publish news {news_id}")
                return False

        except Exception as e:
            logger.error(f"Error publishing news {news_id}: {e}")
            return False

    async def update_moderation_message(self, bot: Bot, chat_id: str, message_id: int,
                                        news_item: dict, news_id: str) -> bool:
        """Update moderation message after editing."""
        try:
            updated_text = self.format_moderation_message(news_item, news_id, edited=True)
            keyboard = self.create_moderation_keyboard(news_id)

            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=updated_text,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )

            logger.info(f"Moderation message updated for news {news_id}")
            return True

        except TelegramError as e:
            logger.error(f"Failed to update moderation message for news {news_id}: {e}")
            return False

    def get_circuit_breaker_stats(self) -> dict:
        """Get circuit breaker statistics."""
        stats = self.circuit_breaker.stats
        return {
            "state": self.circuit_breaker.state.value,
            "failure_count": stats.failure_count,
            "success_count": stats.success_count,
            "total_requests": stats.total_requests,
            "last_failure_time": stats.last_failure_time,
            "success_rate": (stats.success_count / max(stats.total_requests, 1)) * 100
        }

    async def health_check(self, bot: Bot) -> dict:
        """Perform health check on Telegram service."""
        health_info = {
            "telegram_api": "unknown",
            "circuit_breaker": self.circuit_breaker.state.value,
            "cache_size": len(self._message_cache)
        }

        try:
            # Test API connectivity
            bot_info = await bot.get_me()
            health_info["telegram_api"] = "healthy"
            health_info["bot_username"] = bot_info.username

        except Exception as e:
            health_info["telegram_api"] = "unhealthy"
            health_info["error"] = str(e)

        return health_info