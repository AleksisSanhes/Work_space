import logging
import json
import os
import re
import asyncio
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
# Конфигурация
TOKEN = "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8"  # Замените на реальный токен
MODERATION_CHANNEL = "..." # Идентификатор канала Бот: @tg_FlowH2_bot (ID: 8217915867) Тип источника: user, ID отправителя: 6105807855, Имя отправителя: FlowH2, Username: @FlowH2, Ваш ID: 6105807855
PUBLISH_CHANNEL = "..."  # Идентификатор канала
# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# База данных для хранения статуса новостей
NEWS_DB = {}


def clean_telegram_html(text: str) -> str:
    """Очищает текст от неподдерживаемых HTML-тегов"""
    if not text:
        return ""

    # Сначала заменяем теги <p> на переносы строк
    text = text.replace('<p>', '\n\n').replace('</p>', '\n\n')
    text = text.replace('<P>', '\n\n').replace('</P>', '\n\n')

    # Удаляем все другие HTML-теги
    text = re.sub(r'<[^>]+>', '', text)

    # Заменяем HTML-сущности
    replacements = {
        '&amp;': '&',
        '&lt;': '<',
        '&gt;': '>',
        '&quot;': '"',
        '&#39;': "'",
        '&nbsp;': ' ',
    }

    for entity, char in replacements.items():
        text = text.replace(entity, char)

    return text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    await update.message.reply_text("Бот для модерации новостей запущен!")


async def send_to_moderation(news_item: dict) -> None:
    """Отправляет новость в канал модерации"""
    bot = Bot(TOKEN)

    # Очищаем текст от неподдерживаемых тегов
    cleaned_title = clean_telegram_html(news_item.get('title', 'Без заголовка'))
    cleaned_preview = clean_telegram_html(news_item.get('preview', ''))

    # Форматирование сообщения
    message_text = (
        f"<b>{cleaned_title}</b>\n\n"
        f"<b>Источник:</b> {news_item.get('source', 'Неизвестный источник')}\n"
        f"<b>Дата:</b> {news_item.get('date', 'Без даты')}\n"
        f"<b>Ссылка:</b> <a href='{news_item.get('url', '')}'>Оригинал</a>\n\n"
        f"{cleaned_preview}"
    )

    # Создаем инлайн-кнопки
    keyboard = [
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve_{news_item['id']}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{news_item['id']}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        # Отправка в канал модерации
        message = await bot.send_message(
            chat_id=MODERATION_CHANNEL,
            text=message_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

        # Сохраняем данные для последующей модерации
        NEWS_DB[news_item['id']] = {
            'message_id': message.message_id,
            'news_data': news_item
        }
        logger.info(f"Отправлена новость ID: {news_item['id']}")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        logger.error(f"Текст сообщения: {message_text[:200]}...")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    if len(parts) < 2:
        await query.edit_message_text("Неверный формат команды")
        return

    action, news_id = parts[0], parts[1]
    news_data = NEWS_DB.get(news_id)

    if not news_data:
        await query.edit_message_text("Новость не найдена!")
        return

    # Удаляем кнопки после выбора
    await query.edit_message_reply_markup(reply_markup=None)

    try:
        if action == "approve":
            # Пересылаем в основной канал
            await context.bot.send_message(
                chat_id=PUBLISH_CHANNEL,
                text=format_news_for_publication(news_data['news_data']),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            await query.edit_message_text(
                f"✅ Новость опубликована!\n\n{query.message.text}",
                parse_mode="HTML"
            )
            logger.info(f"Опубликована новость ID: {news_id}")
        elif action == "reject":
            await query.edit_message_text(
                f"❌ Новость отклонена!\n\n{query.message.text}",
                parse_mode="HTML"
            )
            logger.info(f"Отклонена новость ID: {news_id}")
    except Exception as e:
        logger.error(f"Ошибка обработки кнопки: {e}")
        await query.edit_message_text("⚠️ Произошла ошибка при обработке")


def format_news_for_publication(news_item: dict) -> str:
    """Форматирует новость для публикации"""
    # Очищаем текст от неподдерживаемых тегов
    cleaned_title = clean_telegram_html(news_item.get('title', 'Без заголовка'))
    cleaned_text = clean_telegram_html(news_item.get('full_text', ''))
    cleaned_source = clean_telegram_html(news_item.get('source', 'Неизвестный источник'))

    # Обрезаем текст если слишком длинный
    if len(cleaned_text) > 3800:
        cleaned_text = cleaned_text[:3800] + "... [сообщение обрезано]"

    return (
        f"<b>🔥 {cleaned_title}</b>\n\n"
        f"{cleaned_text}\n\n"
        f"<i>Источник: {cleaned_source}</i>\n"
        f"<a href='{news_item.get('url', '')}'>Оригинал статьи</a>"
    )


async def load_and_send_news(application: Application) -> None:
    """Загружает новости из JSON и отправляет на модерацию"""
    files = [f for f in os.listdir() if f.startswith('energy_news') and f.endswith('.json')]
    if not files:
        logger.warning("Не найдены JSON-файлы с новостями")
        return

    latest_file = max(files, key=os.path.getctime)
    logger.info(f"Используется файл новостей: {latest_file}")

    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            news_data = json.load(f)

        logger.info(f"Загружено {len(news_data)} новостей")

        for i, news_item in enumerate(news_data):
            # Проверяем наличие обязательных полей
            if not all(key in news_item for key in ['title', 'source', 'date', 'url', 'preview', 'full_text']):
                logger.warning(f"Пропущена новость {i} из-за отсутствия обязательных полей")
                continue

            # Добавляем уникальный ID
            news_item['id'] = f"{datetime.now().strftime('%Y%m%d%H%M')}_{i}"
            await send_to_moderation(news_item)
            # Небольшая задержка между отправками, чтобы не перегружать API
            await asyncio.sleep(0.3)

    except Exception as e:
        logger.error(f"Ошибка загрузки новостей: {e}")
        logger.exception("Детали ошибки:")


async def post_init(application: Application) -> None:
    """Функция инициализации после запуска бота"""
    await load_and_send_news(application)


def main() -> None:
    """Запуск бота"""
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен")
    application.run_polling()


if __name__ == '__main__':
    main()