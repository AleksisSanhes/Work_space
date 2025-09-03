# bot/handlers/message_handlers.py
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class MessageHandlers:
    """Handlers for text messages."""

    def __init__(self, database, telegram_service):
        self.db = database
        self.telegram = telegram_service

    async def edit_text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages for news editing."""
        if not update.message or not update.message.text:
            return

        logger.debug(f"Received text message: {update.message.text[:100]}...")

        # Check if user data exists and has editing state
        if not context.user_data:
            logger.debug("No user data available")
            return

        news_id = context.user_data.get("editing_news_id")
        if not news_id:
            logger.debug("No active editing session")
            return

        try:
            # Handle skip command
            if update.message.text.strip() == "/skip":
                await self._handle_skip_edit(update, context, news_id)
                return

            # Process the edited text
            await self._process_edited_text(update, context, news_id)

        except Exception as e:
            logger.error(f"Edit text handler error: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ Ошибка обработки текста: {str(e)}")
            # Clear editing state on error
            context.user_data["editing_news_id"] = None

    async def _handle_skip_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE, news_id: str):
        """Handle skip editing command."""
        context.user_data["editing_news_id"] = None
        await update.message.reply_text("✅ Редактирование пропущено.")
        logger.info(f"Editing skipped for news {news_id}")

    async def _process_edited_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, news_id: str):
        """Process the edited text for a news item."""
        new_text = update.message.text.strip()

        # Get news data
        data_entry = self.db.get_news(news_id)
        if not data_entry:
            await update.message.reply_text("⚠️ Новость не найдена в базе.")
            context.user_data["editing_news_id"] = None
            return

        # Update news data in database
        try:
            # Update the full text and mark as edited
            self.db.news_db[news_id]["news_data"]["full_text"] = new_text
            self.db.news_db[news_id]["news_data"]["edited"] = True

            # Clean up old preview messages if they exist
            news_item = data_entry["news_data"]
            preview_ids = news_item.get("preview_message_ids")
            preview_chat_id = news_item.get("preview_chat_id")

            if preview_ids and preview_chat_id:
                # Delete preview messages
                if hasattr(self.telegram, 'safe_delete_messages'):
                    await self.telegram.safe_delete_messages(
                        context.bot, preview_chat_id, preview_ids, news_id
                    )
                else:
                    # Fallback manual deletion
                    for msg_id in preview_ids:
                        try:
                            await context.bot.delete_message(chat_id=preview_chat_id, message_id=msg_id)
                        except Exception:
                            pass

                # Clear preview info
                self.db.news_db[news_id]["news_data"]["preview_message_ids"] = []
                self.db.news_db[news_id]["news_data"]["preview_chat_id"] = None

            # Save changes
            self.db.save_db()

        except Exception as e:
            logger.error(f"Error updating news {news_id}: {e}")
            await update.message.reply_text(f"⚠️ Ошибка сохранения изменений: {str(e)}")
            context.user_data["editing_news_id"] = None
            return

        # Update moderation message
        try:
            channel_id = data_entry["channel_id"]
            message_id = data_entry["message_id"]

            if message_id:
                # Get updated news item
                updated_news_item = self.db.news_db[news_id]["news_data"]

                # Format updated message
                def safe_escape_text(text):
                    if not text:
                        return ""
                    import re
                    text = re.sub(r'<[^>]+>', '', str(text))
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text

                title = safe_escape_text(updated_news_item.get("title", ""))
                preview = safe_escape_text(updated_news_item.get("preview", ""))
                source = safe_escape_text(updated_news_item.get("source", ""))
                date = safe_escape_text(updated_news_item.get("date", ""))
                url = updated_news_item.get('url', '')

                updated_text = (
                    f"📰 {title} ✏️ ОТРЕДАКТИРОВАНО\n\n"
                    f"{preview}\n\n"
                    f"Источник: {source} ({date})\n"
                    f"{url}"
                )

                # Create new keyboard
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve|{news_id}"),
                        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject|{news_id}"),
                        InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit|{news_id}")
                    ]
                ]

                await context.bot.edit_message_text(
                    chat_id=channel_id,
                    message_id=message_id,
                    text=updated_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    disable_web_page_preview=True
                )

                await update.message.reply_text(
                    "✅ Текст новости обновлён и сообщение в канале модерации обновлено!\n"
                    "Теперь нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
                )

            else:
                await update.message.reply_text(
                    "✅ Текст новости обновлён!\n"
                    "⚠️ Сообщение в канале модерации не найдено, но изменения сохранены."
                )

        except Exception as update_error:
            logger.error(f"Error updating moderation message: {update_error}")
            await update.message.reply_text(
                "✅ Текст новости обновлён!\n"
                "⚠️ Не удалось обновить сообщение в канале модерации, но изменения сохранены.\n"
                "Нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
            )

        # Clear editing state
        context.user_data["editing_news_id"] = None
        logger.info(f"News {news_id} text updated successfully")