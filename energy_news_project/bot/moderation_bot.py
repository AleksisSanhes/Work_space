import os
import json
import asyncio
import html
import re
import hashlib
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import re
import asyncio
import logging
from telegram.error import TelegramError, RetryAfter

logger = logging.getLogger(__name__)


TOKEN = "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8"
MODERATION_CHANNEL = "-1002996332660"
PUBLISH_CHANNEL = "-1003006895565"

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
SENT_IDS_FILE = os.path.join(DATA_DIR, "sent_ids.json")
NEWS_DB_FILE = os.path.join(DATA_DIR, "news_db.json")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

NEWS_DB = {}  # {id: {... данные ...}}

# ---------- Утилиты ----------
def make_news_id(item, index=0):
    key = (item.get("url") or "").strip()
    if not key:
        key = f"{item.get('title','')}-{item.get('date','')}".strip()
    if not key:
        key = item.get("preview", "")[:120]
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def safe_clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------- Работа с файлами ----------
def load_sent_ids() -> set:
    if os.path.exists(SENT_IDS_FILE):
        with open(SENT_IDS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent_ids(sent_ids: set):
    os.makedirs(os.path.dirname(SENT_IDS_FILE), exist_ok=True)
    with open(SENT_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_ids), f, ensure_ascii=False)


def load_news_db():
    global NEWS_DB
    if os.path.exists(NEWS_DB_FILE):
        with open(NEWS_DB_FILE, "r", encoding="utf-8") as f:
            NEWS_DB = json.load(f)
        logger.info(f"Загружено NEWS_DB ({len(NEWS_DB)} записей).")


def save_news_db():
    os.makedirs(os.path.dirname(NEWS_DB_FILE), exist_ok=True)
    with open(NEWS_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(NEWS_DB, f, ensure_ascii=False)


# ---------- Отправка с задержкой ----------
async def send_with_delay(bot, chat_id, text, reply_markup=None, pause: float = 1.5, max_retries: int = 5):
    """
    Отправка сообщения с учётом паузы и обработки Flood control.
    Если Telegram возвращает RetryAfter, ждём нужное время и повторяем.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(pause)  # обычная пауза между сообщениями
            return message
        except RetryAfter as e:
            # Telegram просит подождать N секунд
            wait_time = e.retry_after
            logger.warning(f"Flood control: ждём {wait_time} секунд перед повторной отправкой...")
            await asyncio.sleep(wait_time)
            attempt += 1
        except TelegramError as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
            return None
    logger.error(f"Не удалось отправить сообщение после {max_retries} попыток.")
    return None


# ---------- Telegram Handlers ----------
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

    message = await send_with_delay(bot, MODERATION_CHANNEL, text, reply_markup=InlineKeyboardMarkup(keyboard))

    if message:
        NEWS_DB[news_item["id"]] = {
            "message_id": message.message_id,
            "news_data": news_item,
            "channel_id": MODERATION_CHANNEL,
        }
        sent_ids.add(news_item["id"])
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

        save_news_db()

    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await query.edit_message_text(f"⚠️ Ошибка: {e}")


# ---------- Основные функции работы ----------
async def load_and_send_news(bot: Bot):
    load_news_db()
    sent_ids = load_sent_ids()

    while True:
        print("\nВыберите режим:")
        print("1) Загрузить новые новости")
        print("2) Только слушать кнопки")
        print("3) Очистить канал Публикации")
        print("4) Очистить канал Модерации")
        print("5) Очистить NEWS_DB и sent_ids.json")

        choice = input("Введите 1, 2, 3, 4 или 5: ").strip()

        files = [os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR) if f.startswith("energy_news") and f.endswith(".json")]
        latest_file = max(files, key=os.path.getctime) if files else None

        if choice == "1":
            if not latest_file:
                print("❗ Нет файлов energy_news*.json")
                continue
            with open(latest_file, "r", encoding="utf-8") as f:
                news_list = json.load(f)

            count = 0
            for i, item in enumerate(news_list):
                if not all(k in item for k in ["title", "source", "date", "url", "preview", "full_text"]):
                    continue
                item_id = make_news_id(item, i)
                if item_id in sent_ids:
                    continue
                item["id"] = item_id
                await send_to_moderation(bot, item, sent_ids)
                count += 1
            print(f"Отправлено в модерацию: {count} новых новостей.")

        elif choice == "2":
            print("Режим только слушать кнопки.")
            if not latest_file:
                print("❗ Нет файлов energy_news*.json")
                continue
            with open(latest_file, "r", encoding="utf-8") as f:
                news_list = json.load(f)
            for i, item in enumerate(news_list):
                item_id = make_news_id(item, i)
                if item_id not in NEWS_DB:
                    NEWS_DB[item_id] = {"message_id": None, "news_data": item, "channel_id": MODERATION_CHANNEL}
            save_news_db()
            break  # только слушаем кнопки, выходим из цикла

        elif choice == "3":
            print(f"Очищаем канал {PUBLISH_CHANNEL}...")
            for news_id, entry in list(NEWS_DB.items()):
                if entry["channel_id"] == PUBLISH_CHANNEL and entry["message_id"]:
                    try:
                        await bot.delete_message(PUBLISH_CHANNEL, entry["message_id"])
                        del NEWS_DB[news_id]
                    except Exception as e:
                        print(f"Ошибка удаления {entry['message_id']}: {e}")
            save_news_db()
            print("Канал очищен.")

        elif choice == "4":
            print(f"Очищаем канал {MODERATION_CHANNEL}...")
            for news_id, entry in list(NEWS_DB.items()):
                if entry["channel_id"] == MODERATION_CHANNEL and entry["message_id"]:
                    try:
                        await bot.delete_message(MODERATION_CHANNEL, entry["message_id"])
                        del NEWS_DB[news_id]
                    except Exception as e:
                        print(f"Ошибка удаления {entry['message_id']}: {e}")
            save_news_db()
            print("Канал очищен.")

        elif choice == "5":
            if os.path.exists(NEWS_DB_FILE):
                os.remove(NEWS_DB_FILE)
            if os.path.exists(SENT_IDS_FILE):
                os.remove(SENT_IDS_FILE)
            NEWS_DB.clear()
            print("NEWS_DB и sent_ids.json очищены.")

        else:
            print("❌ Неверный выбор. Попробуйте снова.")


# ---------- Post init ----------
async def post_init(app: Application):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"Не удалось удалить webhook: {e}")

    await load_and_send_news(app.bot)


# ---------- Запуск бота ----------
def run_bot():
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("testpublish", test_publish_command))
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(approve|reject)\|"))
    application.run_polling()
