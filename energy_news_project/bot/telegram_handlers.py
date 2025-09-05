# bot/telegram_handlers.py
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from bot.formatters import format_news_for_publication

logger = logging.getLogger(__name__)

# Global store for editing sessions (handles context issues)
EDITING_SESSIONS = {}


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


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, db, telegram_service):
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
            await _handle_approve(query, context, db, news_id, data_entry, telegram_service)
        elif action == "reject":
            await _handle_reject(query, context, db, news_id, data_entry, telegram_service)
        elif action == "edit":
            # Обработка редактирования напрямую здесь
            news_item = data_entry["news_data"]
            full_text = news_item.get("full_text", "")

            if full_text:
                # Отправляем заголовок
                header_message = await query.message.reply_text(
                    f"📝 Текущий полный текст новости (ID: {news_id}):"
                )

                # Отправляем текст частями используя telegram_service
                text_message_ids = await telegram_service.split_and_send_message(
                    context.bot, query.message.chat_id, full_text
                )
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


async def _handle_approve(query, context, db, news_id, data_entry, telegram_service):
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

    edit_status = " (отредактированной)" if news_item.get("edited", False) else ""

    try:
        # Публикуем в канал используя telegram_service
        success = await telegram_service.publish_news(context.bot, news_item, news_id)

        if success:
            logger.info(f"Новость {news_id} успешно опубликована в канал")

            # Уведомление модератору
            try:
                await query.message.reply_text(f"✅ Новость {news_id} успешно опубликована{edit_status}!")
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление модератору: {e}")

            # Очистка превью сообщений используя telegram_service
            if news_item.get("preview_message_ids") and news_item.get("preview_chat_id"):
                await telegram_service.safe_delete_messages(
                    context.bot,
                    news_item["preview_chat_id"],
                    news_item["preview_message_ids"],
                    news_id
                )

            # Удаление сообщения модерации используя telegram_service
            await telegram_service.safe_delete_messages(context.bot, channel_id, [message_id], news_id)

            # Удаление из базы данных
            db.delete_news(news_id)
            logger.info(f"Новость {news_id} опубликована{edit_status} и удалена из модерации")
        else:
            await query.edit_message_text("❌ Ошибка при публикации новости.")

    except Exception as e:
        logger.error(f"Ошибка публикации новости {news_id}: {e}")
        try:
            await query.edit_message_text(f"❌ Ошибка публикации: {e}")
        except Exception:
            await query.message.reply_text(f"❌ Ошибка публикации: {e}")


async def _handle_reject(query, context, db, news_id, data_entry, telegram_service):
    """Обработка отклонения новости."""
    news_item = data_entry["news_data"]
    channel_id = data_entry["channel_id"]
    message_id = data_entry["message_id"]

    try:
        await query.message.reply_text(f"❌ Новость {news_id} отклонена и удалена.")
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление об отклонении: {e}")

    # Очистка превью сообщений используя telegram_service
    if news_item.get("preview_message_ids") and news_item.get("preview_chat_id"):
        await telegram_service.safe_delete_messages(
            context.bot,
            news_item["preview_chat_id"],
            news_item["preview_message_ids"],
            news_id
        )

    # Удаление сообщения модерации используя telegram_service
    await telegram_service.safe_delete_messages(context.bot, channel_id, [message_id], news_id)

    # Удаление из базы данных
    db.delete_news(news_id)
    logger.info(f"Новость {news_id} отклонена и удалена из модерации")


async def edit_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, db, telegram_service):
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

    # Очистка старых превью сообщений используя telegram_service
    if data_entry["news_data"].get("preview_message_ids") and data_entry["news_data"].get("preview_chat_id"):
        await telegram_service.safe_delete_messages(
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

    # Обновляем сообщение в канале модерации используя telegram_service
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

        # Используем telegram_service для обновления сообщения модерации
        success = await telegram_service.update_moderation_message(
            context.bot, channel_id, message_id, news_item, news_id
        )

        if success:
            await update.message.reply_text(
                "✅ Текст новости обновлён и сообщение в канале модерации обновлено!\n"
                "Теперь нажмите кнопку 'Опубликовать' для публикации отредактированной версии."
            )
        else:
            await update.message.reply_text(
                "✅ Текст новости обновлён!\n"
                "⚠️ Не удалось обновить сообщение в канале модерации, но изменения сохранены."
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