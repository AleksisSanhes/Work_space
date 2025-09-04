# bot/telegram_handlers.py
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from bot.telegram_bot import PUBLISH_CHANNEL
from bot.formatters import format_news_for_publication

logger = logging.getLogger(__name__)

# Global store for editing sessions (handles context issues)
EDITING_SESSIONS = {}


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
            await asyncio.sleep(0.5)
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
                    await asyncio.sleep(0.5)
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
            await asyncio.sleep(0.1)
        except TelegramError as e:
            logger.warning(f"Не удалось удалить сообщение {message_id} для новости {news_id}: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при удалении сообщения {message_id}: {e}")

    logger.info(f"Удалено {deleted_count} из {len(message_ids)} сообщений для новости {news_id}")
    return deleted_count


def _safe_escape_html(text):
    """Безопасное экранирование HTML."""
    if not text:
        return ""
    import re
    text = re.sub(r'<[^>]+>', '', str(text))
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _update_news_database(db, news_id, updates):
    """Универсальная функция для обновления базы данных (поддерживает старую и новую версии)."""
    if hasattr(db, 'update_news'):
        # Новая база данных - попробуем два способа
        try:
            return db.update_news(news_id, updates)
        except Exception as e:
            logger.error(f"Ошибка обновления через update_news: {e}")
            # Fallback к прямому обновлению
            if news_id in db.news_db:
                for key, value in updates.items():
                    if '.' in key:
                        parts = key.split('.')
                        current = db.news_db[news_id]
                        for part in parts[:-1]:
                            if part not in current:
                                current[part] = {}
                            current = current[part]
                        current[parts[-1]] = value
                    else:
                        db.news_db[news_id][key] = value
                db.save_db()
                return True
            return False
    else:
        # Старая база данных
        if news_id in db.news_db:
            for key, value in updates.items():
                if '.' in key:
                    # Обработка вложенных ключей типа "news_data.full_text"
                    parts = key.split('.')
                    current = db.news_db[news_id]
                    for part in parts[:-1]:
                        if part not in current:
                            current[part] = {}
                        current = current[part]
                    current[parts[-1]] = value
                    logger.info(f"Обновили {key} = {value[:100] if isinstance(value, str) else value}")
                else:
                    db.news_db[news_id][key] = value

            # Принудительно сохраняем
            db.save_db()

            # Проверим что данные действительно обновились
            updated_item = db.get_news(news_id)
            if updated_item:
                for key, expected_value in updates.items():
                    if '.' in key:
                        parts = key.split('.')
                        current = updated_item
                        for part in parts:
                            current = current.get(part, {})
                        actual_value = current if not isinstance(current, dict) else current.get(parts[-1])
                        logger.info(
                            f"Проверка обновления {key}: ожидали {expected_value[:100] if isinstance(expected_value, str) else expected_value}, получили {actual_value[:100] if isinstance(actual_value, str) else actual_value}")

            return True
        return False


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, db):
    """Обработчик нажатий кнопок."""
    query = update.callback_query
    await query.answer()

    try:
        action, news_id = query.data.split("|", 1)
        logger.info(f"Обрабатываем действие: {action} для новости {news_id}")

        # Всегда получаем свежие данные из базы
        data_entry = db.get_news(news_id)
        if not data_entry:
            await query.edit_message_text("⚠️ Запись не найдена.")
            return

        if action == "approve":
            await _handle_approve(query, context, db, news_id, data_entry)
        elif action == "reject":
            await _handle_reject(query, context, db, news_id, data_entry)
        elif action == "edit":
            # Обработка редактирования напрямую здесь
            news_item = data_entry["news_data"]
            full_text = news_item.get("full_text", "")

            if full_text:
                # Отправляем заголовок
                header_message = await query.message.reply_text(
                    f"📝 Текущий полный текст новости (ID: {news_id}):"
                )

                # Отправляем текст частями
                text_message_ids = await split_and_send_text(context.bot, query.message.chat_id, full_text)
                all_preview_ids = [header_message.message_id] + text_message_ids

                # Сохраняем ID превью сообщений
                updates = {
                    "news_data.preview_message_ids": all_preview_ids,
                    "news_data.preview_chat_id": query.message.chat_id
                }
                _update_news_database(db, news_id, updates)

                logger.info(f"Сохранены ID сообщений с превью для новости {news_id}: {all_preview_ids}")
            else:
                preview_message = await query.message.reply_text("⚠️ Полный текст новости отсутствует.")
                updates = {
                    "news_data.preview_message_ids": [preview_message.message_id],
                    "news_data.preview_chat_id": query.message.chat_id
                }
                _update_news_database(db, news_id, updates)

            await query.message.reply_text(
                "✏️ Отправьте исправленный текст новости.\n"
                "Чтобы оставить как есть — отправьте /skip\n"
                "⚠️ После редактирования сообщение в канале модерации будет обновлено."
            )

            # Сохраняем состояние редактирования
            user_id = update.effective_user.id if update.effective_user else "unknown"
            EDITING_SESSIONS[user_id] = news_id

            if context.user_data is not None:
                context.user_data["editing_news_id"] = news_id

    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        try:
            await query.edit_message_text(f"⚠️ Ошибка: {e}")
        except Exception:
            await query.message.reply_text(f"⚠️ Ошибка: {e}")


async def _handle_approve(query, context, db, news_id, data_entry):
    """Обработка одобрения новости."""
    # Получаем свежие данные перед публикацией
    fresh_data_entry = db.get_news(news_id)
    if not fresh_data_entry:
        await query.edit_message_text("⚠️ Запись не найдена.")
        return

    news_item = fresh_data_entry["news_data"]
    channel_id = fresh_data_entry["channel_id"]
    message_id = fresh_data_entry["message_id"]

    # Дополнительное логирование для отладки
    logger.info(f"Публикуем новость {news_id}, full_text: {news_item.get('full_text', '')[:100]}...")
    logger.info(f"Edited flag: {news_item.get('edited', False)}")

    publication_text = format_news_for_publication(news_item)
    edit_status = " (отредактированной)" if news_item.get("edited", False) else ""

    # Логируем финальный текст для публикации
    logger.info(f"Финальный текст для публикации: {publication_text[:200]}...")

    try:
        # Публикуем в канал
        await context.bot.send_message(
            chat_id=PUBLISH_CHANNEL,
            text=publication_text,
            disable_web_page_preview=True,
        )
        logger.info(f"Новость {news_id} успешно опубликована в канал")

        # Уведомление модератору
        try:
            await query.message.reply_text(f"✅ Новость {news_id} успешно опубликована{edit_status}!")
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление модератору: {e}")

        # Очистка превью сообщений
        if news_item.get("preview_message_ids") and news_item.get("preview_chat_id"):
            await safe_delete_messages(
                context.bot,
                news_item["preview_chat_id"],
                news_item["preview_message_ids"],
                news_id
            )

        # Удаление сообщения модерации
        await safe_delete_messages(context.bot, channel_id, [message_id], news_id)

        # Удаление из базы данных
        db.delete_news(news_id)
        logger.info(f"Новость {news_id} опубликована{edit_status} и удалена из модерации")

    except Exception as e:
        logger.error(f"Ошибка публикации новости {news_id}: {e}")
        try:
            await query.edit_message_text(f"❌ Ошибка публикации: {e}")
        except Exception:
            await query.message.reply_text(f"❌ Ошибка публикации: {e}")


async def _handle_reject(query, context, db, news_id, data_entry):
    """Обработка отклонения новости."""
    news_item = data_entry["news_data"]
    channel_id = data_entry["channel_id"]
    message_id = data_entry["message_id"]

    try:
        await query.message.reply_text(f"❌ Новость {news_id} отклонена и удалена.")
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление об отклонении: {e}")

    # Очистка превью сообщений
    if news_item.get("preview_message_ids") and news_item.get("preview_chat_id"):
        await safe_delete_messages(
            context.bot,
            news_item["preview_chat_id"],
            news_item["preview_message_ids"],
            news_id
        )

    # Удаление сообщения модерации
    await safe_delete_messages(context.bot, channel_id, [message_id], news_id)

    # Удаление из базы данных
    db.delete_news(news_id)
    logger.info(f"Новость {news_id} отклонена и удалена из модерации")


async def edit_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, db):
    """Обработчик редактирования текста."""
    logger.info(f"edit_text_handler вызван с текстом: {update.message.text[:100]}")

    user_id = update.effective_user.id if update.effective_user else "unknown"

    # Проверяем глобальные сессии редактирования
    news_id = EDITING_SESSIONS.get(user_id)

    # Также проверяем контекст
    if not news_id and context.user_data:
        news_id = context.user_data.get("editing_news_id")

    logger.info(f"user_id: {user_id}, editing_news_id: {news_id}")

    if not news_id:
        logger.info("Нет активного редактирования, пропускаем")
        return

    if update.message.text.strip() == "/skip":
        await update.message.reply_text("✅ Редактирование пропущено.")
        _clear_editing_session(user_id, context)
        return

    # Получаем данные новости
    data_entry = db.get_news(news_id)
    if not data_entry:
        await update.message.reply_text("⚠️ Новость не найдена в базе.")
        _clear_editing_session(user_id, context)
        return

    # Обновляем текст новости - ПРЯМОЕ обновление без функций-оберток
    logger.info(f"ПЕРЕД обновлением: новость {news_id}")
    logger.info(f"Обновляем full_text на: '{update.message.text}'")
    logger.info(f"Обновляем edited на: True")

    # Прямое обновление базы данных
    if hasattr(db, 'news_db') and news_id in db.news_db:
        # Прямой доступ к структуре данных
        db.news_db[news_id]["news_data"]["full_text"] = update.message.text
        db.news_db[news_id]["news_data"]["edited"] = True

        # Принудительное сохранение
        if hasattr(db, 'save_db'):
            db.save_db()

        logger.info("✅ Прямое обновление выполнено")
    else:
        logger.error("❌ Не удалось найти news_db или новость")

    # Проверим что данные действительно обновились
    verification_entry = db.get_news(news_id)
    if verification_entry:
        actual_full_text = verification_entry["news_data"].get("full_text", "")
        actual_edited = verification_entry["news_data"].get("edited", False)
        logger.info(f"ПРОВЕРКА ПОСЛЕ обновления:")
        logger.info(f"Actual full_text: '{actual_full_text[:100]}...'")
        logger.info(f"Actual edited: {actual_edited}")

        if actual_full_text == update.message.text and actual_edited == True:
            logger.info("✅ Данные успешно обновлены!")
        else:
            logger.error("❌ ДАННЫЕ НЕ ОБНОВИЛИСЬ!")
    else:
        logger.error("❌ Не удалось получить данные для проверки!")

    # Очистка старых превью сообщений
    if data_entry["news_data"].get("preview_message_ids") and data_entry["news_data"].get("preview_chat_id"):
        await safe_delete_messages(
            context.bot,
            data_entry["news_data"]["preview_chat_id"],
            data_entry["news_data"]["preview_message_ids"],
            news_id
        )
        # Очищаем список превью
        clear_updates = {
            "news_data.preview_message_ids": [],
            "news_data.preview_chat_id": None
        }
        _update_news_database(db, news_id, clear_updates)

    logger.info(f"Текст новости {news_id} обновлен")

    # Обновляем сообщение в канале модерации
    try:
        channel_id = data_entry["channel_id"]
        message_id = data_entry["message_id"]

        if message_id is None:
            logger.warning(f"Нельзя обновить сообщение для новости {news_id}: message_id is None")
            await update.message.reply_text(
                "✅ Текст новости обновлён!\n"
                "⚠️ Сообщение в канале модерации не найдено, но изменения сохранены."
            )
            _clear_editing_session(user_id, context)
            return

        # Получаем свежие данные
        fresh_data_entry = db.get_news(news_id)
        news_item = fresh_data_entry["news_data"]

        # Формируем обновленный текст
        clean_title = _safe_escape_html(news_item.get("title", ""))
        clean_preview = _safe_escape_html(news_item.get("preview", ""))
        clean_source = _safe_escape_html(news_item.get("source", ""))
        clean_date = _safe_escape_html(news_item.get("date", ""))
        clean_url = news_item.get('url', '')

        keyboard = [
            [
                InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve|{news_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject|{news_id}"),
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit|{news_id}")
            ]
        ]

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
        )

        await update.message.reply_text(
            "✅ Текст новости обновлён и сообщение в канале модерации обновлено!\n"
            "Теперь нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
        )

    except Exception as e:
        logger.error(f"Ошибка обновления сообщения в канале модерации: {e}")
        await update.message.reply_text(
            "✅ Текст новости обновлён!\n"
            "⚠️ Не удалось обновить сообщение в канале модерации, но изменения сохранены."
        )

    _clear_editing_session(user_id, context)


def _clear_editing_session(user_id, context):
    """Очистка сессии редактирования."""
    EDITING_SESSIONS.pop(user_id, None)
    if context.user_data:
        context.user_data["editing_news_id"] = None


async def skip_edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /skip."""
    user_id = update.effective_user.id if update.effective_user else "unknown"

    news_id = EDITING_SESSIONS.get(user_id)
    if not news_id and context.user_data:
        news_id = context.user_data.get("editing_news_id")

    if news_id:
        _clear_editing_session(user_id, context)
        await update.message.reply_text("✅ Редактирование пропущено.")
    else:
        await update.message.reply_text("ℹ️ Нет активного процесса редактирования.")