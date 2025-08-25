import logging
import json
import os
import re
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import RetryAfter
import html
import hashlib


# Конфигурация
TOKEN = "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8"
MODERATION_CHANNEL = "-1002996332660"
PUBLISH_CHANNEL = "-1003006895565"
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Файлы для хранения
SENT_IDS_FILE = "sent_ids.json"
NEWS_DB_FILE = "news_db.json"

NEWS_DB = {}  # {id: {... данные ...}}


def make_news_id(item, index=0):
    """Генерация детерминированного ID для новости"""
    # Берём URL, если есть
    key = (item.get("url") or "").strip()
    if not key:
        # fallback: title+date
        key = f"{item.get('title','')}-{item.get('date','')}".strip()
    if not key:
        # fallback: preview (обрезаем)
        key = item.get("preview", "")[:120]

    # Возвращаем короткий sha256-хеш (16 символов)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

def safe_clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------- ЧТЕНИЕ / ЗАПИСЬ файлов ----------

def load_sent_ids() -> set:
    if os.path.exists(SENT_IDS_FILE):
        with open(SENT_IDS_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()


def save_sent_ids(sent_ids: set):
    with open(SENT_IDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(sent_ids), f, ensure_ascii=False)


def load_news_db():
    global NEWS_DB
    if os.path.exists(NEWS_DB_FILE):
        with open(NEWS_DB_FILE, 'r', encoding='utf-8') as f:
            NEWS_DB = json.load(f)
        logger.info(f"Загружено NEWS_DB из файла ({len(NEWS_DB)} записей).")


def save_news_db():
    with open(NEWS_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(NEWS_DB, f, ensure_ascii=False)


# =============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен.")


async def test_publish_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=PUBLISH_CHANNEL, text="🔔 Тестовая публикация")
        await update.message.reply_text("Отправлено (если бот имеет доступ к каналу).")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при публикации: {e}")


async def send_to_moderation(bot: Bot, news_item: dict, sent_ids: set):
    title = safe_clean_text(news_item.get("title", "Без заголовка"))
    source = safe_clean_text(news_item.get("source", "Неизвестный источник"))
    date = safe_clean_text(news_item.get("date", ""))
    preview = safe_clean_text(news_item.get("preview", ""))
    url = news_item.get("url", "")

    text = f"{title}\n\nИсточник: {source}\nДата: {date}\nСсылка: {url}\n\n{preview}"
    keyboard = [
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve|{news_item['id']}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject|{news_item['id']}"),
        ]
    ]
    message = await bot.send_message(
        chat_id=MODERATION_CHANNEL,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )

    NEWS_DB[news_item['id']] = {
        "message_id": message.message_id,
        "news_data": news_item,
        "channel_id": MODERATION_CHANNEL,
    }
    sent_ids.add(news_item['id'])
    logger.info(f"Новость {news_item['id']} отправлена в модерацию.")
    save_news_db()
    save_sent_ids(sent_ids)


def format_news_for_publication(news_item: dict) -> str:
    title = safe_clean_text(news_item.get("title", "Без заголовка"))
    text = safe_clean_text(news_item.get("full_text", ""))
    source = safe_clean_text(news_item.get("source", "Источник не указан"))
    url = news_item.get("url", "")

    if len(text) > 3800:
        text = text[:3800] + "... [обрезано]"

    return f"🔥 {title}\n\n{text}\n\nИсточник: {source}\nОригинал: {url}"


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, news_id = query.data.split("|", 1)
        data_entry = NEWS_DB.get(news_id)
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
                reply_markup=None
            )
            logger.info(f"Новость {news_id} опубликована.")

        elif action == "reject":
            await context.bot.edit_message_text(
                chat_id=channel_id,
                message_id=message_id,
                text=f"❌ ОТКЛОНЕНО\n\n{query.message.text}",
                reply_markup=None
            )
            logger.info(f"Новость {news_id} отклонена.")

        save_news_db()  # Обновить файл базы после изменений

    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await query.edit_message_text(f"⚠️ Ошибка: {e}")


async def load_and_send_news_if_requested(bot: Bot, sent_ids: set):
    # Попросим пользователя
    answer = input(
        "\nВыберите режим:\n"
        "1) Загрузить новые новости\n"
        "2) Только слушать кнопки\n"
        "Введите 1 или 2: "
    ).strip()

    if answer != "1":
        print("Новости не будут загружаться. Бот только слушает кнопки.")
        return

    # --- Если "1" ---
    print("Загрузка новостей из файлов...")

    files = [f for f in os.listdir() if f.startswith("energy_news") and f.endswith(".json")]
    if not files:
        print("❗ Нет файлов energy_news*.json")
        return

    latest_file = max(files, key=os.path.getctime)
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            news_list = json.load(f)
    except Exception as e:
        print("Не удалось прочитать файл:", e)
        return

    count = 0
    for i, item in enumerate(news_list):
        if not all(k in item for k in ["title", "source", "date", "url", "preview", "full_text"]):
            continue
        # генерируем id
        item_id = make_news_id(item, i)
        if item_id in sent_ids:
            continue
        item["id"] = item_id
        # отправляем
        await send_to_moderation(bot, item, sent_ids)
        count += 1
        await asyncio.sleep(2)

    print(f"Отправлено в модерацию: {count} новых новостей.")


async def shutdown_previous_webhook(bot: Bot):
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook удалён (если был).")
    except Exception as e:
        logger.warning(f"Не удалось удалить webhook: {e}")


async def post_init(app: Application):
    await shutdown_previous_webhook(app.bot)
    # загружаем базу, отправляем новости по желанию
    load_news_db()
    sent_ids = load_sent_ids()
    await load_and_send_news_if_requested(app.bot, sent_ids)


def main():
    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("testpublish", test_publish_command))
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(approve|reject)\|"))

    application.run_polling()


if __name__ == "__main__":
    main()