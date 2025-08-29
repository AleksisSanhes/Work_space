import asyncio
import logging
from telegram import Bot
from telegram.error import TelegramError

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8"  # Ваш токен


async def get_channel_info():
    bot = Bot(TOKEN)
    try:
        # Получаем информацию о боте
        me = await bot.get_me()
        logger.info(f"Бот: @{me.username} (ID: {me.id})")

        # Получаем последние обновления
        updates = await bot.get_updates(limit=100, timeout=30)

        if not updates:
            logger.warning("Не найдено обновлений. Попробуйте следующее:")
            logger.warning("1. Отправьте ЛЮБОЕ сообщение в канал")
            logger.warning("2. Добавьте бота в канал как администратора")
            logger.warning("3. Перезапустите скрипт")
            return

        logger.info(f"Найдено {len(updates)} обновлений")

        # Ищем сообщения из каналов
        channel_found = False
        for update in updates:
            if update.channel_post:
                chat = update.channel_post.chat
                logger.info("\n" + "=" * 50)
                logger.info("НАЙДЕН КАНАЛ!")
                logger.info(f"ID: {chat.id}")
                logger.info(f"Название: {chat.title}")
                logger.info(f"Тип: {chat.type}")
                logger.info("=" * 50)
                channel_found = True

        if not channel_found:
            logger.warning("Сообщений от каналов не найдено!")
            logger.warning("Убедитесь что:")
            logger.warning("- Бот является администратором канала")
            logger.warning("- Вы отправили сообщение в канал ПОСЛЕ добавления бота")

    except TelegramError as e:
        logger.error(f"Ошибка Telegram API: {str(e)}")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {str(e)}")


async def main():
    await get_channel_info()


if __name__ == '__main__':
    # Создаем новый цикл событий для Python 3.10+
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main())
    finally:
        loop.close()