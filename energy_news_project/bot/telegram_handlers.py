import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from bot.telegram_bot import PUBLISH_CHANNEL
from bot.formatters import format_news_for_publication, safe_clean_text
from bot.db import NewsDB

logger = logging.getLogger(__name__)


async def split_and_send_text(bot, chat_id, text, max_length=4000):
    """
    Разбивает длинный текст на части и отправляет несколько сообщений.
    """
    if len(text) <= max_length:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            await asyncio.sleep(0.5)  # Небольшая задержка
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
        return

    # Разбиваем по предложениям для лучшей читаемости
    sentences = text.split('. ')
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk + sentence + '. ') <= max_length:
            current_chunk += sentence + '. '
        else:
            if current_chunk:
                try:
                    await bot.send_message(chat_id=chat_id, text=current_chunk.strip())
                    await asyncio.sleep(0.5)  # Задержка между сообщениями
                except Exception as e:
                    logger.error(f"Ошибка отправки части сообщения: {e}")
                current_chunk = sentence + '. '
            else:
                # Если предложение слишком длинное, разбиваем принудительно
                while len(sentence) > max_length:
                    try:
                        await bot.send_message(chat_id=chat_id, text=sentence[:max_length])
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"Ошибка отправки длинного сообщения: {e}")
                    sentence = sentence[max_length:]
                current_chunk = sentence + '. ' if sentence else ""

    # Отправляем остаток
    if current_chunk:
        try:
            await bot.send_message(chat_id=chat_id, text=current_chunk.strip())
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка отправки остатка сообщения: {e}")


# --- Обработчик нажатий кнопок ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, db: NewsDB):
    query = update.callback_query
    await query.answer()
    try:
        action, news_id = query.data.split("|", 1)
        logger.info(f"Обрабатываем действие: {action} для новости {news_id}")

        data_entry = db.get_news(news_id)
        if not data_entry:
            await query.edit_message_text("⚠️ Запись не найдена.")
            return

        channel_id = data_entry["channel_id"]
        message_id = data_entry["message_id"]
        news_item = data_entry["news_data"]

        if action == "approve":
            news_item = data_entry["news_data"]
            publication_text = format_news_for_publication(news_item)

            # Проверяем, была ли новость отредактирована
            edit_status = " (ОТРЕДАКТИРОВАНО)" if news_item.get("edited", False) else ""

            # Публикуем в канал
            logger.info(f"Начинаем публикацию в канал {PUBLISH_CHANNEL}")
            await context.bot.send_message(
                chat_id=PUBLISH_CHANNEL,
                text=publication_text,
                disable_web_page_preview=True,
            )
            logger.info(f"Успешно опубликовано в канал")

            # Пытаемся обновить сообщение в модерации
            try:
                # Очищаем текст для безопасного отображения
                clean_title = safe_clean_text(news_item.get("title", ""))
                clean_preview = safe_clean_text(news_item.get("preview", ""))
                clean_source = safe_clean_text(news_item.get("source", ""))
                clean_date = safe_clean_text(news_item.get("date", ""))

                original_message = (
                    f"📰 {clean_title}\n\n"
                    f"{clean_preview}\n\n"
                    f"Источник: {clean_source} ({clean_date})\n"
                    f"{news_item.get('url', '')}"
                )

                await context.bot.edit_message_text(
                    chat_id=channel_id,
                    message_id=message_id,
                    text=f"✅ ОПУБЛИКОВАНО{edit_status}\n\n{original_message}",
                    reply_markup=None,
                )
            except Exception as edit_error:
                logger.warning(f"Не удалось обновить сообщение в модерации: {edit_error}")
                # Если не можем отредактировать, отправляем новое сообщение
                await context.bot.send_message(
                    chat_id=channel_id,
                    text=f"✅ Новость {news_id} опубликована{edit_status.lower()}"
                )

            logger.info(f"Новость {news_id} опубликована{edit_status.lower()}.")

        elif action == "reject":
            await context.bot.edit_message_text(
                chat_id=channel_id,
                message_id=message_id,
                text=f"❌ ОТКЛОНЕНО\n\n{query.message.text}",
                reply_markup=None,
            )
            logger.info(f"Новость {news_id} отклонена.")

        elif action == "edit":
            # Показываем полный текст статьи в нескольких сообщениях
            full_text = news_item.get("full_text", "")
            if full_text:
                await query.message.reply_text(
                    f"📝 Текущий полный текст новости (ID: {news_id}):"
                )
                await split_and_send_text(context.bot, query.message.chat_id, full_text)
            else:
                await query.message.reply_text("⚠️ Полный текст новости отсутствует.")

            await query.message.reply_text(
                "✏️ Отправьте исправленный текст новости.\n"
                "Чтобы оставить как есть — отправьте /skip"
            )
            context.user_data["editing_news_id"] = news_id

    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await query.edit_message_text(f"⚠️ Ошибка: {e}")


# --- Обработчик редактирования текста ---
async def edit_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, db: NewsDB):
    logger.info(f"edit_text_handler вызван с текстом: {update.message.text[:100]}")
    logger.info(f"user_data: {context.user_data}")

    # Проверяем, что user_data не None
    if context.user_data is None:
        logger.warning("User data is None, skipping edit handling")
        return

    news_id = context.user_data.get("editing_news_id")
    logger.info(f"editing_news_id: {news_id}")

    if not news_id:
        logger.info("Нет активного редактирования, пропускаем")
        return

    if update.message.text == "/skip":
        await update.message.reply_text("Редактирование пропущено.")
        context.user_data["editing_news_id"] = None
        return

    # Обновляем текст новости
    db.news_db[news_id]["news_data"]["full_text"] = update.message.text
    # Помечаем, что новость была отредактирована
    db.news_db[news_id]["news_data"]["edited"] = True
    db.save_db()

    # Отладочная информация
    logger.info(f"Текст новости {news_id} обновлен на: {update.message.text[:100]}")

    await update.message.reply_text(
        "✅ Текст новости обновлён! Теперь нажмите кнопку 'Опубликовать' для публикации отредактированной версии.")

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