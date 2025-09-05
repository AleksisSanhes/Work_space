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

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Import configuration and services
from config import config
from bot.database import SafeNewsDB
from bot.services.telegram_service import TelegramService
from bot.handlers import BotHandlers
from bot.cli import load_and_send_news

logger.info("Using SafeNewsDB and unified BotHandlers")

# Check token
if not config.telegram.bot_token:
    logger.error("TELEGRAM_BOT_TOKEN not found!")
    sys.exit(1)

# Initialize database and services
db = SafeNewsDB(
    db_file=config.database.db_file,
    sent_ids_file=config.database.sent_ids_file,
    backup_interval=config.database.backup_interval
)

telegram_service = TelegramService(config.telegram)

# Initialize unified handlers
handlers = BotHandlers(db, telegram_service)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by Updates."""
    logger.error("Exception while handling an update:", exc_info=context.error)


async def post_init(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"Не удалось удалить webhook: {e}")

    # Start news loading task
    asyncio.create_task(load_and_send_news(db, app.bot, telegram_service))


def run_bot():
    logger.info("Starting Telegram News Bot")

    application = Application.builder().token(config.telegram.bot_token).post_init(post_init).build()

    # Command handlers
    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("stats", handlers.stats_command))
    application.add_handler(CommandHandler("health", handlers.health_command))
    application.add_handler(CommandHandler("testpublish", handlers.test_publish_command))
    application.add_handler(CommandHandler("skip", handlers.skip_edit_command))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(
        handlers.button_handler,
        pattern=r"^(approve|reject|edit)\|"
    ))

    # Message handlers
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handlers.edit_text_handler
    ))

    # Error handler
    application.add_error_handler(error_handler)

    logger.info("Bot starting...")

    try:
        application.run_polling(
            drop_pending_updates=True,
            close_loop=False
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot runtime error: {e}")
    finally:
        # Cleanup
        logger.info("Shutting down...")
        try:
            db.force_save()
            logger.info("Database saved before shutdown")
        except Exception as e:
            logger.error(f"Error saving database: {e}")


if __name__ == "__main__":
    run_bot()