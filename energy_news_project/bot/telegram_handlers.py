# bot/telegram_handlers.py
import logging
from telegram import Update
from telegram.ext import ContextTypes
from bot.telegram_bot import format_news_for_publication, PUBLISH_CHANNEL
from bot.db import NewsDB

logger = logging.getLogger(__name__)

# --- Обработчик нажатий кнопок ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, db: NewsDB):
    query = update.callback_query
    await query.answer()
    try:
        action, news_id = query.data.split("|", 1)
        data_entry = db.get_news(news_id)
        if not data_entry:
            await query.edit_message_text("⚠️ Запись не найдена.")
            return

        channel_id = data_entry["channel_id"]
        message_id = data_entry["message_id"]
        news_item = data_entry["news_data"]

        if action == "approve":
            publication_text = format_news_for_publication(news_item)
            await context.bot.send_message(
                chat_id=PUBLISH_CHANNEL,
                text=publication_text,
                disable_web_page_preview=True,
            )
            await context.bot.edit_message_text(
                chat_id=channel_id,
                message_id=message_id,
                text=f"✅ ОПУБЛИКОВАНО\n\n{query.message.text}",
                reply_markup=None,
            )
            logger.info(f"Новость {news_id} опубликована.")

        elif action == "reject":
            await context.bot.edit_message_text(
                chat_id=channel_id,
                message_id=message_id,
                text=f"❌ ОТКЛОНЕНО\n\n{query.message.text}",
                reply_markup=None,
            )
            logger.info(f"Новость {news_id} отклонена.")

        elif action == "edit":
            await query.message.reply_text(
                "✏️ Отправьте исправленный текст новости.\n"
                "Чтобы оставить как есть — отправьте /skip",
                reply_markup=None
            )
            context.user_data["editing_news_id"] = news_id

    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await query.edit_message_text(f"⚠️ Ошибка: {e}")


# --- Обработчик редактирования текста ---
async def edit_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, db: NewsDB):
    # Проверяем, что user_data не None
    if context.user_data is None:
        logger.warning("User data is None, skipping edit handling")
        return

    news_id = context.user_data.get("editing_news_id")
    if not news_id:
        return

    if update.message.text == "/skip":
        await update.message.reply_text("Редактирование пропущено.")
    else:
        db.news_db[news_id]["news_data"]["full_text"] = update.message.text
        db.save_db()
        await update.message.reply_text("Текст новости обновлён.")

    context.user_data["editing_news_id"] = None


# --- Обработчик команды /skip ---
async def skip_edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, что user_data не None
    if context.user_data is None:
        logger.warning("User data is None, skipping skip command")
        return

    news_id = context.user_data.get("editing_news_id")
    if news_id:
        context.user_data["editing_news_id"] = None
        await update.message.reply_text("Редактирование пропущено.")