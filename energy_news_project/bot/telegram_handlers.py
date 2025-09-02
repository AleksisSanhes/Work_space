import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from bot.telegram_bot import PUBLISH_CHANNEL
from bot.formatters import format_news_for_publication, safe_clean_text
from bot.db import NewsDB

logger = logging.getLogger(__name__)


async def split_and_send_text(bot, chat_id, text, max_length=4000):
    """
    Разбивает длинный текст на части и отправляет несколько сообщений.
    Возвращает список ID отправленных сообщений.
    """
    message_ids = []

    if len(text) <= max_length:
        try:
            message = await bot.send_message(chat_id=chat_id, text=text)
            if message:
                message_ids.append(message.message_id)
            await asyncio.sleep(0.5)  # Небольшая задержка
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
        return message_ids

    # Разбиваем по предложениям для лучшей читаемости
    sentences = text.split('. ')
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk + sentence + '. ') <= max_length:
            current_chunk += sentence + '. '
        else:
            if current_chunk:
                try:
                    message = await bot.send_message(chat_id=chat_id, text=current_chunk.strip())
                    if message:
                        message_ids.append(message.message_id)
                    await asyncio.sleep(0.5)  # Задержка между сообщениями
                except Exception as e:
                    logger.error(f"Ошибка отправки части сообщения: {e}")
                current_chunk = sentence + '. '
            else:
                # Если предложение слишком длинное, разбиваем принудительно
                while len(sentence) > max_length:
                    try:
                        message = await bot.send_message(chat_id=chat_id, text=sentence[:max_length])
                        if message:
                            message_ids.append(message.message_id)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"Ошибка отправки длинного сообщения: {e}")
                    sentence = sentence[max_length:]
                current_chunk = sentence + '. ' if sentence else ""

    # Отправляем остаток
    if current_chunk:
        try:
            message = await bot.send_message(chat_id=chat_id, text=current_chunk.strip())
            if message:
                message_ids.append(message.message_id)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка отправки остатка сообщения: {e}")

    return message_ids


async def safe_delete_messages(bot, chat_id, message_ids, news_id):
    """
    Безопасное удаление множественных сообщений с обработкой ошибок.
    """
    if not message_ids:
        logger.warning(f"Нет сообщений для удаления для новости {news_id}")
        return 0

    deleted_count = 0
    for message_id in message_ids:
        if message_id is None:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            deleted_count += 1
            logger.info(f"Сообщение {message_id} для новости {news_id} удалено")
            await asyncio.sleep(0.1)  # Небольшая задержка между удалениями
        except TelegramError as e:
            logger.warning(f"Не удалось удалить сообщение {message_id} для новости {news_id}: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при удалении сообщения {message_id}: {e}")

    logger.info(f"Удалено {deleted_count} из {len(message_ids)} сообщений для новости {news_id}")
    return deleted_count


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
            # Получаем свежие данные новости из базы
            data_entry = db.get_news(news_id)
            if not data_entry:
                await query.edit_message_text("⚠️ Запись не найдена.")
                return

            news_item = data_entry["news_data"]
            publication_text = format_news_for_publication(news_item)

            # Проверяем, была ли новость отредактирована
            edit_status = " (ОТРЕДАКТИРОВАНО)" if news_item.get("edited", False) else ""

            # Публикуем в канал
            logger.info(f"Начинаем публикацию в канал {PUBLISH_CHANNEL}")
            try:
                await context.bot.send_message(
                    chat_id=PUBLISH_CHANNEL,
                    text=publication_text,
                    disable_web_page_preview=True,
                )
                logger.info(f"Успешно опубликовано в канал")

                # Отправляем уведомление о публикации в личку модератору (если возможно)
                try:
                    await query.message.reply_text(f"✅ Новость {news_id} успешно опубликована{edit_status.lower()}!")
                except Exception as notify_error:
                    logger.warning(f"Не удалось отправить уведомление модератору: {notify_error}")

                # Удаляем основное сообщение из канала модерации
                message_ids_to_delete = [message_id]

                # Добавляем ID сообщений с полным текстом, если они есть
                if news_item.get("preview_message_ids") and news_item.get("preview_chat_id"):
                    # Сначала удаляем сообщения превью из личного чата
                    await safe_delete_messages(
                        context.bot,
                        news_item["preview_chat_id"],
                        news_item["preview_message_ids"],
                        news_id
                    )
                    logger.info(
                        f"Удалены сообщения превью из личного чата {news_item['preview_chat_id']}: {news_item['preview_message_ids']}")

                # Удаляем основное сообщение из канала модерации
                await safe_delete_messages(context.bot, channel_id, [message_id], news_id)

                # Удаляем запись из базы данных
                db.delete_news(news_id)
                logger.info(f"Новость {news_id} опубликована{edit_status.lower()} и удалена из модерации.")

            except Exception as publish_error:
                logger.error(f"Ошибка публикации новости {news_id}: {publish_error}")
                try:
                    await query.edit_message_text(f"❌ Ошибка публикации: {publish_error}")
                except Exception:
                    await query.message.reply_text(f"❌ Ошибка публикации: {publish_error}")

        elif action == "reject":
            # Получаем свежие данные новости из базы
            data_entry = db.get_news(news_id)
            if not data_entry:
                await query.edit_message_text("⚠️ Запись не найдена.")
                return

            news_item = data_entry["news_data"]

            # Отправляем уведомление о отклонении (если возможно)
            try:
                await query.message.reply_text(f"❌ Новость {news_id} отклонена и удалена.")
            except Exception as notify_error:
                logger.warning(f"Не удалось отправить уведомление об отклонении: {notify_error}")

            # Удаляем основное сообщение и все связанные сообщения
            if news_item.get("preview_message_ids") and news_item.get("preview_chat_id"):
                # Сначала удаляем сообщения превью из личного чата
                await safe_delete_messages(
                    context.bot,
                    news_item["preview_chat_id"],
                    news_item["preview_message_ids"],
                    news_id
                )
                logger.info(
                    f"Удалены сообщения превью из личного чата {news_item['preview_chat_id']}: {news_item['preview_message_ids']}")

            # Удаляем основное сообщение из канала модерации
            await safe_delete_messages(context.bot, channel_id, [message_id], news_id)

            # Удаляем запись из базы данных
            db.delete_news(news_id)
            logger.info(f"Новость {news_id} отклонена и удалена из модерации.")

        elif action == "edit":
            # Показываем полный текст статьи в нескольких сообщениях
            full_text = news_item.get("full_text", "")
            if full_text:
                # Отправляем заголовок
                header_message = await query.message.reply_text(
                    f"📝 Текущий полный текст новости (ID: {news_id}):"
                )

                # Отправляем текст частями и сохраняем ID всех сообщений
                text_message_ids = await split_and_send_text(context.bot, query.message.chat_id, full_text)

                # Сохраняем ID всех сообщений с превью И chat_id в базе данных
                all_preview_ids = [header_message.message_id] + text_message_ids
                db.news_db[news_id]["news_data"]["preview_message_ids"] = all_preview_ids
                db.news_db[news_id]["news_data"]["preview_chat_id"] = query.message.chat_id
                db.save_db()

                logger.info(
                    f"Сохранены ID сообщений с превью для новости {news_id}: {all_preview_ids} в чате {query.message.chat_id}")
            else:
                preview_message = await query.message.reply_text("⚠️ Полный текст новости отсутствует.")
                # Сохраняем ID этого сообщения тоже
                db.news_db[news_id]["news_data"]["preview_message_ids"] = [preview_message.message_id]
                db.news_db[news_id]["news_data"]["preview_chat_id"] = query.message.chat_id
                db.save_db()

            await query.message.reply_text(
                "✏️ Отправьте исправленный текст новости.\n"
                "Чтобы оставить как есть — отправьте /skip\n"
                "⚠️ После редактирования сообщение в канале модерации будет обновлено."
            )
            context.user_data["editing_news_id"] = news_id

    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        try:
            await query.edit_message_text(f"⚠️ Ошибка: {e}")
        except Exception:
            # Если не можем отредактировать, отправляем новое сообщение
            await query.message.reply_text(f"⚠️ Ошибка: {e}")


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
        await update.message.reply_text("✅ Редактирование пропущено.")
        context.user_data["editing_news_id"] = None
        return

    # Получаем данные новости
    data_entry = db.get_news(news_id)
    if not data_entry:
        await update.message.reply_text("⚠️ Новость не найдена в базе.")
        context.user_data["editing_news_id"] = None
        return

    # Обновляем текст новости
    db.news_db[news_id]["news_data"]["full_text"] = update.message.text
    # Помечаем, что новость была отредактирована
    db.news_db[news_id]["news_data"]["edited"] = True

    # Удаляем старые сообщения с превью, если они есть
    # ВАЖНО: превью отправляются в личный чат, получаем правильный chat_id
    if data_entry["news_data"].get("preview_message_ids") and data_entry["news_data"].get("preview_chat_id"):
        await safe_delete_messages(
            context.bot,
            data_entry["news_data"]["preview_chat_id"],  # Используем сохраненный chat_id
            data_entry["news_data"]["preview_message_ids"],
            news_id
        )
        # Очищаем список ID сообщений с превью и chat_id
        db.news_db[news_id]["news_data"]["preview_message_ids"] = []
        db.news_db[news_id]["news_data"]["preview_chat_id"] = None

    db.save_db()

    # Отладочная информация
    logger.info(f"Текст новости {news_id} обновлен на: {update.message.text[:100]}")

    # Обновляем сообщение в канале модерации
    try:
        channel_id = data_entry["channel_id"]
        message_id = data_entry["message_id"]
        news_item = data_entry["news_data"]

        # Проверяем, что message_id существует
        if message_id is None:
            logger.warning(f"Нельзя обновить сообщение для новости {news_id}: message_id is None")
            await update.message.reply_text(
                "✅ Текст новости обновлён!\n"
                "⚠️ Сообщение в канале модерации не найдено, но изменения сохранены.\n"
                "Нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
            )
            context.user_data["editing_news_id"] = None
            return

        # Функция для безопасного экранирования HTML
        def safe_escape_html(text):
            if not text:
                return ""
            # Сначала удаляем все HTML-теги
            import re
            text = re.sub(r'<[^>]+>', '', str(text))
            # Затем экранируем специальные символы
            return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        # Безопасно обрабатываем текст для отображения
        clean_title = safe_escape_html(news_item.get("title", ""))
        clean_preview = safe_escape_html(news_item.get("preview", ""))
        clean_source = safe_escape_html(news_item.get("source", ""))
        clean_date = safe_escape_html(news_item.get("date", ""))
        clean_url = news_item.get('url', '')

        # Создаем новую кнопочную панель
        keyboard = [
            [
                InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve|{news_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject|{news_id}"),
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit|{news_id}")
            ]
        ]

        # Формируем текст без HTML-парсинга для избежания ошибок
        updated_text = (
            f"📰 {clean_title} ✏️ ОТРЕДАКТИРОВАНО\n\n"
            f"{clean_preview}\n\n"
            f"Источник: {clean_source} ({clean_date})\n"
            f"{clean_url}"
        )

        await context.bot.edit_message_text(
            chat_id=channel_id,
            message_id=message_id,
            text=updated_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
            # Убираем parse_mode='HTML' чтобы избежать ошибок парсинга
        )

        await update.message.reply_text(
            "✅ Текст новости обновлён и сообщение в канале модерации обновлено!\n"
            "Теперь нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
        )

    except Exception as update_error:
        logger.error(f"Ошибка обновления сообщения в канале модерации: {update_error}")
        await update.message.reply_text(
            "✅ Текст новости обновлён!\n"
            "⚠️ Не удалось обновить сообщение в канале модерации, но изменения сохранены.\n"
            "Нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
        )

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
        await update.message.reply_text("✅ Редактирование пропущено.")
    else:
        await update.message.reply_text("ℹ️ Нет активного процесса редактирования.")