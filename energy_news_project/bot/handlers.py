# bot/handlers.py
import logging
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from bot.database import SafeNewsDB
from bot.services.telegram_service import TelegramService
from bot.formatters import format_news_for_publication

logger = logging.getLogger(__name__)


class BotHandlers:
    """Unified handlers for all bot interactions."""

    def __init__(self, database: SafeNewsDB, telegram_service: TelegramService):
        self.db = database
        self.telegram = telegram_service

    # ===== CALLBACK HANDLERS =====
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback button presses from moderation messages."""
        query = update.callback_query
        if not query:
            return

        await query.answer()

        try:
            # Parse callback data
            if "|" not in query.data:
                await query.edit_message_text("⚠️ Неверный формат данных кнопки.")
                return

            action, news_id = query.data.split("|", 1)
            logger.info(f"Processing action: {action} for news: {news_id}")

            # Get news data
            data_entry = self.db.get_news(news_id)
            if not data_entry:
                await query.edit_message_text("⚠️ Новость не найдена в базе данных.")
                return

            # Route to appropriate handler
            if action == "approve":
                await self._handle_approve(query, news_id, data_entry, context)
            elif action == "reject":
                await self._handle_reject(query, news_id, data_entry, context)
            elif action == "edit":
                await self._handle_edit(query, news_id, data_entry, context)
            else:
                await query.edit_message_text(f"⚠️ Неизвестное действие: {action}")

        except Exception as e:
            logger.error(f"Callback handler error: {e}", exc_info=True)
            try:
                await query.edit_message_text(f"⚠️ Ошибка обработки: {str(e)}")
            except TelegramError:
                # If edit fails, try to send a new message
                await query.message.reply_text(f"⚠️ Ошибка обработки: {str(e)}")

    async def _handle_approve(self, query, news_id: str, data_entry: dict, context: ContextTypes.DEFAULT_TYPE):
        """Handle news approval and publication."""
        try:
            news_item = data_entry["news_data"]
            channel_id = data_entry["channel_id"]
            message_id = data_entry["message_id"]

            edit_status = " (отредактированной)" if news_item.get("edited", False) else ""

            # Publish to main channel
            success = await self.telegram.publish_news(context.bot, news_item, news_id)

            if success:
                # Clean up preview messages if they exist (check if they weren't already cleaned)
                preview_ids = news_item.get("preview_message_ids")
                preview_chat_id = news_item.get("preview_chat_id")

                if preview_ids and preview_chat_id:
                    logger.info(f"Cleaning up remaining preview messages for news {news_id}")
                    await self._cleanup_preview_messages(news_item, context.bot, news_id)

                # Delete moderation message
                await self.telegram.safe_delete_messages(
                    context.bot, channel_id, [message_id], news_id
                )

                # Update database
                self.db.update_news(news_id, {"status": "published"})

                # Skip sending any notifications to avoid Bad Request
                logger.info(f"News {news_id} successfully approved and published{edit_status} - notifications disabled")
                # Remove from database after successful publication
                self.db.delete_news(news_id)

                logger.info(f"News {news_id} approved and published{edit_status}")

            else:
                await query.edit_message_text("❌ Ошибка при публикации новости.")

        except Exception as e:
            logger.error(f"Approve handler error for {news_id}: {e}")
            await query.edit_message_text(f"❌ Ошибка публикации: {str(e)}")

    async def _handle_reject(self, query, news_id: str, data_entry: dict, context: ContextTypes.DEFAULT_TYPE):
        """Handle news rejection and cleanup."""
        try:
            news_item = data_entry["news_data"]
            channel_id = data_entry["channel_id"]
            message_id = data_entry["message_id"]

            # Clean up preview messages if they exist
            await self._cleanup_preview_messages(news_item, context.bot, news_id)

            # Delete moderation message
            await self.telegram.safe_delete_messages(
                context.bot, channel_id, [message_id], news_id
            )

            # Update database
            self.db.update_news(news_id, {"status": "rejected"})

            # Log successful rejection
            logger.info(f"News {news_id} successfully rejected and removed")

            # Remove from database
            self.db.delete_news(news_id)

            logger.info(f"News {news_id} rejected and removed")

        except Exception as e:
            logger.error(f"Reject handler error for {news_id}: {e}")
            await query.edit_message_text(f"❌ Ошибка отклонения: {str(e)}")

    async def _handle_edit(self, query, news_id: str, data_entry: dict, context: ContextTypes.DEFAULT_TYPE):
        """Handle edit request - show full text and prepare for editing."""
        try:
            news_item = data_entry["news_data"]
            full_text = news_item.get("full_text", "")

            if full_text:
                # Send header message
                header_msg = await query.message.reply_text(
                    f"📝 Текущий полный текст новости (ID: {news_id}):"
                )

                # Send full text in chunks
                text_message_ids = await self.telegram.split_and_send_message(
                    context.bot, query.message.chat_id, full_text
                )

                # Store preview message IDs
                all_preview_ids = [header_msg.message_id] + text_message_ids

                # Update news data with preview info
                updates = {
                    "news_data.preview_message_ids": all_preview_ids,
                    "news_data.preview_chat_id": query.message.chat_id
                }
                self.db.update_news(news_id, updates)

                logger.info(f"Preview messages sent for news {news_id}: {all_preview_ids}")

            else:
                # No full text available
                preview_msg = await query.message.reply_text("⚠️ Полный текст новости отсутствует.")

                updates = {
                    "news_data.preview_message_ids": [preview_msg.message_id],
                    "news_data.preview_chat_id": query.message.chat_id
                }
                self.db.update_news(news_id, updates)

            # Send edit instructions
            await query.message.reply_text(
                "✏️ Отправьте исправленный текст новости.\n"
                "Чтобы оставить как есть — отправьте /skip\n"
                "⚠️ После редактирования сообщение в канале модерации будет обновлено."
            )

            # Set editing state
            if context.user_data is not None:
                context.user_data["editing_news_id"] = news_id

        except Exception as e:
            logger.error(f"Edit handler error for {news_id}: {e}")
            await query.edit_message_text(f"❌ Ошибка подготовки к редактированию: {str(e)}")

    async def _cleanup_preview_messages(self, news_item: dict, bot, news_id: str):
        """Clean up preview messages if they exist."""
        preview_ids = news_item.get("preview_message_ids")
        preview_chat_id = news_item.get("preview_chat_id")

        if preview_ids and preview_chat_id:
            await self.telegram.safe_delete_messages(
                bot, preview_chat_id, preview_ids, news_id
            )
            logger.info(f"Cleaned up preview messages for news {news_id}")

    # ===== MESSAGE HANDLERS =====
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

        # Update news data
        updates = {
            "news_data.full_text": new_text,
            "news_data.edited": True,
            "updated_at": None  # Will be set automatically by database
        }

        logger.info(f"Updating news {news_id} with new text: {new_text[:100]}...")

        # Clean up old preview messages
        news_item = data_entry["news_data"]
        preview_ids = news_item.get("preview_message_ids")
        preview_chat_id = news_item.get("preview_chat_id")

        if preview_ids and preview_chat_id:
            await self.telegram.safe_delete_messages(
                context.bot, preview_chat_id, preview_ids, news_id
            )

            # Clear preview info
            updates.update({
                "news_data.preview_message_ids": [],
                "news_data.preview_chat_id": None
            })

        # Save changes
        success = self.db.update_news(news_id, updates)

        # Verify the update was successful
        if success:
            verification = self.db.get_news(news_id)
            if verification:
                actual_text = verification["news_data"].get("full_text", "")
                actual_edited = verification["news_data"].get("edited", False)
                logger.info(f"Verification - text updated: {actual_text == new_text}, edited flag: {actual_edited}")
            else:
                logger.error(f"Could not verify update for news {news_id}")
        else:
            logger.error(f"Failed to update news {news_id}")

        if not success:
            await update.message.reply_text("⚠️ Не удалось обновить новость.")
            context.user_data["editing_news_id"] = None
            return

        # Update moderation message
        channel_id = data_entry["channel_id"]
        message_id = data_entry["message_id"]

        if message_id:
            # Get updated news data
            updated_entry = self.db.get_news(news_id)
            updated_news_item = updated_entry["news_data"] if updated_entry else news_item

            success = await self.telegram.update_moderation_message(
                context.bot, channel_id, message_id, updated_news_item, news_id
            )

            if success:
                await update.message.reply_text(
                    "✅ Текст новости обновлён и сообщение в канале модерации обновлено!\n"
                    "Теперь нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
                )
            else:
                await update.message.reply_text(
                    "✅ Текст новости обновлён!\n"
                    "⚠️ Не удалось обновить сообщение в канале модерации, но изменения сохранены.\n"
                    "Нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
                )
        else:
            await update.message.reply_text(
                "✅ Текст новости обновлён!\n"
                "⚠️ Сообщение в канале модерации не найдено, но изменения сохранены."
            )

        # Clear editing state
        context.user_data["editing_news_id"] = None
        logger.info(f"News {news_id} text updated successfully")

    # ===== COMMAND HANDLERS =====
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome_text = (
            "🤖 Бот модерации энергетических новостей запущен!\n\n"
            "Доступные команды:\n"
            "/help - Показать справку\n"
            "/stats - Показать статистику\n"
            "/health - Проверить состояние системы\n"
            "/testpublish - Тест публикации в канал"
        )

        await update.message.reply_text(welcome_text)
        logger.info(f"Start command from user {update.effective_user.id}")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = (
            "📖 Справка по боту модерации новостей\n\n"
            "🔧 Команды:\n"
            "/start - Запуск бота\n"
            "/help - Эта справка\n"
            "/stats - Статистика базы данных\n"
            "/health - Состояние системы\n"
            "/testpublish - Тестовая публикация\n"
            "/skip - Пропустить редактирование\n\n"
            "📝 Процесс модерации:\n"
            "1. Новости автоматически отправляются в канал модерации\n"
            "2. Используйте кнопки: ✅ Опубликовать, ❌ Отклонить, ✏️ Редактировать\n"
            "3. При редактировании отправьте новый текст или /skip\n\n"
            "⚠️ Все действия логируются для анализа."
        )

        await update.message.reply_text(help_text)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        try:
            db_stats = self.db.get_stats()
            telegram_stats = self.telegram.get_circuit_breaker_stats()

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
            logger.error(f"Stats command error: {e}")
            await update.message.reply_text(f"⚠️ Ошибка получения статистики: {str(e)}")

    async def health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /health command."""
        try:
            health_info = await self.telegram.health_check(context.bot)

            status_emoji = "🟢" if health_info["telegram_api"] == "healthy" else "🔴"

            health_text = (
                f"🏥 Состояние системы\n\n"
                f"{status_emoji} Telegram API: {health_info['telegram_api']}\n"
                f"🔌 Circuit Breaker: {health_info['circuit_breaker']}\n"
                f"💾 Размер кеша: {health_info['cache_size']}\n"
            )

            if "bot_username" in health_info:
                health_text += f"🤖 Бот: @{health_info['bot_username']}\n"

            if "error" in health_info:
                health_text += f"❌ Ошибка: {health_info['error']}\n"

            await update.message.reply_text(health_text)

        except Exception as e:
            logger.error(f"Health command error: {e}")
            await update.message.reply_text(f"⚠️ Ошибка проверки состояния: {str(e)}")

    async def test_publish_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /testpublish command."""
        try:
            test_message = await self.telegram.send_with_retry(
                context.bot,
                self.telegram.config.publish_channel,
                "🔔 Тестовое сообщение от бота модерации"
            )

            if test_message:
                await update.message.reply_text("✅ Тестовое сообщение успешно отправлено в канал публикации.")
            else:
                await update.message.reply_text("❌ Не удалось отправить тестовое сообщение.")

        except Exception as e:
            logger.error(f"Test publish error: {e}")
            await update.message.reply_text(f"⚠️ Ошибка при тестовой публикации: {str(e)}")

    async def skip_edit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /skip command."""
        if not context.user_data:
            await update.message.reply_text("ℹ️ Нет активного процесса редактирования.")
            return

        news_id = context.user_data.get("editing_news_id")
        if news_id:
            context.user_data["editing_news_id"] = None
            await update.message.reply_text("✅ Редактирование пропущено.")
            logger.info(f"Editing skipped for news {news_id}")
        else:
            await update.message.reply_text("ℹ️ Нет активного процесса редактирования.")

    # Admin commands (only if debug mode is enabled)
    async def cleanup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cleanup command (admin only)."""
        try:
            removed_count = self.db.cleanup_old_news(days=30)
            await update.message.reply_text(f"🗑️ Очищено {removed_count} старых новостей.")

        except Exception as e:
            logger.error(f"Cleanup command error: {e}")
            await update.message.reply_text(f"⚠️ Ошибка очистки: {str(e)}")

    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /backup command (admin only)."""
        try:
            self.db.force_save()
            await update.message.reply_text("💾 Принудительное сохранение базы данных выполнено.")

        except Exception as e:
            logger.error(f"Backup command error: {e}")
            await update.message.reply_text(f"⚠️ Ошибка сохранения: {str(e)}")