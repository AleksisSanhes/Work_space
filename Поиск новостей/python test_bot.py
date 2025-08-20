'''
Отлично! 🎉 Это значит:

✅ Callback-кнопки в тестовом боте работают
✅ button_handler вызывается
✅ pattern=r"^(approve|reject)\|" корректный
✅ Проблема НЕ в коде обработчика
'''


from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import logging

TOKEN = "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data="approve|123"),
            InlineKeyboardButton("❌ Отклонить", callback_data="reject|123"),
        ]
    ]
    await update.message.reply_text("Тестовая новость", reply_markup=InlineKeyboardMarkup(keyboard))


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info(f"Нажата кнопка: {query.data}")
    await query.answer("Обработано!")
    await query.edit_message_text(f"Обработано: {query.data}")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback, pattern=r"^(approve|reject)\|"))
    app.run_polling()

if __name__ == "__main__":
    main()
