# bot/bot_runner_simple.py
import asyncio
import logging
import sys
import os
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ChatType

# Create logs directory
os.makedirs("logs", exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.FileHandler("logs/errors.log", encoding="utf-8", mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Filter for error log
error_handler = logging.FileHandler("logs/errors.log", encoding="utf-8")
error_handler.setLevel(logging.ERROR)
logging.getLogger().addHandler(error_handler)

logger = logging.getLogger(__name__)

# Import your existing modules
try:
    from bot.database import SafeNewsDB

    NEW_DATABASE = True
    logger.info("Using new SafeNewsDB")
except ImportError:
    from bot.db import NewsDB as SafeNewsDB

    NEW_DATABASE = False
    logger.info("Using legacy NewsDB")

from bot.cli import load_and_send_news

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8")
MODERATION_CHANNEL = os.getenv("MODERATION_CHANNEL", "-1002996332660")
PUBLISH_CHANNEL = os.getenv("PUBLISH_CHANNEL", "-1003006895565")

if not TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not found!")
    sys.exit(1)

# Initialize database
if NEW_DATABASE:
    db = SafeNewsDB()
else:
    db = NewsDB()
if NEW_DATABASE:
    db = SafeNewsDB()
else:
    db = SafeNewsDB()

# Import handlers
from bot.telegram_handlers import button_handler, edit_text_handler, skip_edit_handler


# Simple command handlers
async def start(update, context):
    await update.message.reply_text(
        "🤖 Бот модерации энергетических новостей запущен!\n\n"
        "Доступные команды:\n"
        "/help - Показать справку\n"
        "/stats - Показать статистику\n"
        "/testpublish - Тест публикации в канал"
    )


async def help_command(update, context):
    help_text = (
        "📖 Справка по боту модерации новостей\n\n"
        "🔧 Команды:\n"
        "/start - Запуск бота\n"
        "/help - Эта справка\n"
        "/stats - Статистика базы данных\n"
        "/testpublish - Тестовая публикация\n"
        "/skip - Пропустить редактирование\n\n"
        "📝 Процесс модерации:\n"
        "1. Новости автоматически отправляются в канал модерации\n"
        "2. Используйте кнопки: ✅ Опубликовать, ❌ Отклонить, ✏️ Редактировать\n"
        "3. При редактировании отправьте новый текст или /skip\n\n"
        "⚠️ Все действия логируются для анализа."
    )
    await update.message.reply_text(help_text)


async def stats_command(update, context):
    try:
        if hasattr(db, 'get_stats'):
            stats = db.get_stats()
            stats_text = (
                f"📊 Статистика системы\n\n"
                f"📰 База данных:\n"
                f"• Всего новостей: {stats.get('total_news', 0)}\n"
                f"• Отправлено: {stats.get('sent_count', 0)}\n"
            )
        else:
            # Legacy database
            total_news = len(db.news_db) if hasattr(db, 'news_db') else 0
            sent_count = len(db.sent_ids) if hasattr(db, 'sent_ids') else 0
            stats_text = (
                f"📊 Статистика системы\n\n"
                f"📰 База данных:\n"
                f"• Всего новостей: {total_news}\n"
                f"• Отправлено: {sent_count}\n"
            )

        await update.message.reply_text(stats_text)
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text(f"⚠️ Ошибка получения статистики: {str(e)}")


async def test_publish_command(update, context):
    try:
        await context.bot.send_message(
            chat_id=PUBLISH_CHANNEL,
            text="🔔 Тестовая публикация"
        )
        await update.message.reply_text("✅ Отправлено (если бот имеет доступ к каналу).")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при публикации: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by Updates."""
    logger.error("Exception while handling an update:", exc_info=context.error)


async def post_init(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"Не удалось удалить webhook: {e}")

    # Запуск консольного меню в отдельной таске
    asyncio.create_task(load_and_send_news(db, app.bot))


def run_bot():
    logger.info("Starting Telegram News Bot")

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("testpublish", test_publish_command))
    application.add_handler(CommandHandler("skip", skip_edit_handler))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(
        lambda u, c: button_handler(u, c, db),
        pattern=r"^(approve|reject|edit)\|"
    ))

    # Message handlers
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        lambda u, c: edit_text_handler(u, c, db)
    ))

    # Error handler
    application.add_error_handler(error_handler)

    logger.info("Bot starting...")

    try:
        application.run_polling(
            drop_pending_updates=True,
            close_loop=False  # Don't close the event loop
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot runtime error: {e}")
    finally:
        # Cleanup
        logger.info("Shutting down...")
        if hasattr(db, 'force_save'):
            try:
                db.force_save()
                logger.info("Database saved before shutdown")
            except Exception as e:
                logger.error(f"Error saving database: {e}")


if __name__ == "__main__":
    run_bot()