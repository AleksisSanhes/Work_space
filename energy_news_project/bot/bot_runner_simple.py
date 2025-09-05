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

# НОВЫЕ ИМПОРТЫ - заменяем старые
from config import config
from bot.database import SafeNewsDB
from bot.services.telegram_service import TelegramService
from bot.cli import load_and_send_news

logger.info("Using SafeNewsDB")

# УДАЛЯЕМ старые константы - теперь в config
# TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8")
# MODERATION_CHANNEL = os.getenv("MODERATION_CHANNEL", "-1002996332660")
# PUBLISH_CHANNEL = os.getenv("PUBLISH_CHANNEL", "-1003006895565")

# Проверяем токен из конфигурации
if not config.telegram.bot_token:
    logger.error("TELEGRAM_BOT_TOKEN not found!")
    sys.exit(1)

# Initialize database and services
db = SafeNewsDB(
    db_file=config.database.db_file,
    sent_ids_file=config.database.sent_ids_file,
    backup_interval=config.database.backup_interval
)

# НОВЫЙ СЕРВИС
telegram_service = TelegramService(config.telegram)

# Import handlers
from bot.telegram_handlers import button_handler, edit_text_handler, skip_edit_handler


# Simple command handlers - ОБНОВЛЯЕМ
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


# ПОЛНОСТЬЮ ПЕРЕПИСЫВАЕМ stats_command
async def stats_command(update, context):
    try:
        db_stats = db.get_stats()
        telegram_stats = telegram_service.get_circuit_breaker_stats()

        stats_text = (
            f"📊 Статистика системы\n\n"
            f"📰 База данных:\n"
            f"• Всего новостей: {db_stats['total_news']}\n"
            f"• Отправлено: {db_stats['sent_count']}\n"
            f"• Ожидает модерации: {db_stats['pending']}\n"
            f"• Опубликовано: {db_stats['published']}\n"
            f"• Отклонено: {db_stats['rejected']}\n"
            f"• Размер БД: {db_stats['db_size_mb']:.2f} МБ\n\n"
            f"📡 Telegram API:\n"
            f"• Статус: {telegram_stats['state']}\n"
            f"• Успешных запросов: {telegram_stats['success_count']}\n"
            f"• Неудачных запросов: {telegram_stats['failure_count']}\n"
            f"• Успешность: {telegram_stats['success_rate']:.1f}%"
        )

        await update.message.reply_text(stats_text)
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text(f"⚠️ Ошибка получения статистики: {str(e)}")


# ПЕРЕПИСЫВАЕМ test_publish_command
async def test_publish_command(update, context):
    try:
        success = await telegram_service.send_with_retry(
            context.bot,
            config.telegram.publish_channel,
            "🔔 Тестовая публикация"
        )

        if success:
            await update.message.reply_text("✅ Тестовое сообщение успешно отправлено.")
        else:
            await update.message.reply_text("❌ Не удалось отправить тестовое сообщение.")
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

    # ОБНОВЛЯЕМ вызов load_and_send_news
    asyncio.create_task(load_and_send_news(db, app.bot, telegram_service))


def run_bot():
    logger.info("Starting Telegram News Bot")

    # ИСПОЛЬЗУЕМ конфигурацию
    application = Application.builder().token(config.telegram.bot_token).post_init(post_init).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("testpublish", test_publish_command))
    application.add_handler(CommandHandler("skip", skip_edit_handler))

    # ОБНОВЛЯЕМ Callback handlers - передаем telegram_service
    application.add_handler(CallbackQueryHandler(
        lambda u, c: button_handler(u, c, db, telegram_service),
        pattern=r"^(approve|reject|edit)\|"
    ))

    # ОБНОВЛЯЕМ Message handlers
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        lambda u, c: edit_text_handler(u, c, db, telegram_service)
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
        try:
            db.force_save()
            logger.info("Database saved before shutdown")
        except Exception as e:
            logger.error(f"Error saving database: {e}")


if __name__ == "__main__":
    run_bot()