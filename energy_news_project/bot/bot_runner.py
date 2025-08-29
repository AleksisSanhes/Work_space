# bot/bot_runner.py
import asyncio
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from bot.db import NewsDB
from bot.telegram_bot import send_to_moderation, make_news_id, PUBLISH_CHANNEL
from bot.telegram_handlers import button_handler, edit_text_handler, skip_edit_handler
from bot.cli import load_and_send_news
from telegram.constants import ChatType


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8"

# Инициализация базы
db = NewsDB()


# --- Команды ---
async def start(update, context):
    await update.message.reply_text("Бот запущен.")

# Добавьте эту функцию в bot_runner.py
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логируем ошибки, вызванные обновлениями."""
    logger.error("Exception while handling an update:", exc_info=context.error)

async def test_publish_command(update, context):
    try:
        await context.bot.send_message(chat_id=PUBLISH_CHANNEL, text="🔔 Тестовая публикация")
        await update.message.reply_text("Отправлено (если бот имеет доступ к каналу).")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при публикации: {e}")


# --- Post init ---
async def post_init(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"Не удалось удалить webhook: {e}")

    # Запуск консольного меню в отдельной таске
    asyncio.create_task(load_and_send_news(db, app.bot))


# --- Запуск бота ---
def run_bot():
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # --- Хэндлеры ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("testpublish", test_publish_command))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: button_handler(u, c, db),
        pattern=r"^(approve|reject|edit)\|"
    ))
    application.add_handler(CommandHandler("skip", skip_edit_handler))
    # Добавьте фильтр приватных чатов к обработчикам
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        lambda u, c: edit_text_handler(u, c, db)
    ))
    application.add_handler(CommandHandler("skip", skip_edit_handler, filters=filters.ChatType.PRIVATE))

    # Добавьте этот обработчик ошибок
    application.add_error_handler(error_handler)

    # --- Запуск ---
    application.run_polling()

if __name__ == "__main__":
    run_bot()
