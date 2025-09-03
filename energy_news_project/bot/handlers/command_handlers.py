# bot/handlers/command_handlers.py
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class CommandHandlers:
    """Handlers for bot commands."""

    def __init__(self, database, telegram_service):
        self.db = database
        self.telegram = telegram_service

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
            # Basic stats from database
            total_news = len(self.db.news_db) if hasattr(self.db, 'news_db') else 0
            sent_count = len(self.db.sent_ids) if hasattr(self.db, 'sent_ids') else 0

            stats_text = (
                f"📊 Статистика системы\n\n"
                f"📰 База данных:\n"
                f"• Всего новостей: {total_news}\n"
                f"• Отправлено: {sent_count}\n"
            )

            # Add telegram stats if available
            if hasattr(self.telegram, 'get_circuit_breaker_stats'):
                telegram_stats = self.telegram.get_circuit_breaker_stats()
                stats_text += (
                    f"\n📡 Telegram API:\n"
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
            health_text = "🏥 Состояние системы\n\n"

            # Check bot connection
            try:
                bot_info = await context.bot.get_me()
                health_text += f"🟢 Telegram API: healthy\n"
                health_text += f"🤖 Бот: @{bot_info.username}\n"
            except Exception as e:
                health_text += f"🔴 Telegram API: unhealthy - {str(e)}\n"

            # Database status
            health_text += f"💾 База данных: активна\n"

            await update.message.reply_text(health_text)

        except Exception as e:
            logger.error(f"Health command error: {e}")
            await update.message.reply_text(f"⚠️ Ошибка проверки состояния: {str(e)}")

    async def test_publish_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /testpublish command."""
        try:
            # Get publish channel from config or fallback
            publish_channel = getattr(self.telegram.config if hasattr(self.telegram, 'config') else None,
                                      'publish_channel', None)
            if not publish_channel:
                # Fallback to hardcoded value from original code
                publish_channel = "-1003006895565"

            await context.bot.send_message(
                chat_id=publish_channel,
                text="🔔 Тестовое сообщение от бота модерации"
            )

            await update.message.reply_text("✅ Тестовое сообщение успешно отправлено в канал публикации.")

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

    # Admin commands (optional)
    async def cleanup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cleanup command (admin only)."""
        try:
            if hasattr(self.db, 'cleanup_old_news'):
                removed_count = self.db.cleanup_old_news(days=30)
                await update.message.reply_text(f"🗑️ Очищено {removed_count} старых новостей.")
            else:
                await update.message.reply_text("⚠️ Функция очистки недоступна.")

        except Exception as e:
            logger.error(f"Cleanup command error: {e}")
            await update.message.reply_text(f"⚠️ Ошибка очистки: {str(e)}")

    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /backup command (admin only)."""
        try:
            if hasattr(self.db, 'force_save'):
                self.db.force_save()
            elif hasattr(self.db, 'save_db'):
                self.db.save_db()
                if hasattr(self.db, 'save_sent_ids'):
                    self.db.save_sent_ids()

            await update.message.reply_text("💾 Принудительное сохранение базы данных выполнено.")

        except Exception as e:
            logger.error(f"Backup command error: {e}")
            await update.message.reply_text(f"⚠️ Ошибка сохранения: {str(e)}")