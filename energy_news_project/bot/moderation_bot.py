import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from .db import NEWS_DB, load_news_db, save_news_db, load_sent_ids, save_sent_ids
from .formatters import safe_clean_text, format_news_for_publication

TOKEN = "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8"
MODERATION_CHANNEL = "-1002996332660"
PUBLISH_CHANNEL = "-1003006895565"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, news_id = query.data.split("|", 1)
        data_entry = NEWS_DB.get(news_id)
        if not data_entry:
            await query.edit_message_text("⚠️ Запись не найдена.")
            return

        news_item = data_entry["news_data"]

        if action == "approve":
            publication_text = format_news_for_publication(news_item)
            await context.bot.send_message(
                chat_id=PUBLISH_CHANNEL,
                text=publication_text,
                disable_web_page_preview=True,
            )
            await query.edit_message_text(f"✅ ОПУБЛИКОВАНО\n\n{query.message.text}")
            logger.info(f"Новость {news_id} опубликована.")

        elif action == "reject":
            await query.edit_message_text(f"❌ ОТКЛОНЕНО\n\n{query.message.text}")
            logger.info(f"Новость {news_id} отклонена.")

        save_news_db()
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await query.edit_message_text(f"⚠️ Ошибка: {e}")

def run_bot():
    load_news_db()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(approve|reject)\|"))
    application.run_polling()
