# bot/cli.py
import os
import json
import asyncio
from bot.db import NewsDB
from bot.telegram_bot import send_to_moderation, make_news_id

DATA_DIR = "data"

async def load_and_send_news(db: NewsDB, bot):
    """
    Консольное меню для загрузки новостей и отправки их в модерацию.
    """
    while True:
        print("\nВыберите действие:")
        print("1) Загрузить новые новости из последнего файла energy_news*.json")
        print("2) Загрузить новости из выбранного файла")
        print("3) Показать количество новостей в базе")
        print("4) Очистить NEWS_DB и sent_ids.json")
        print("0) Выход")

        choice = (await asyncio.to_thread(input, "Введите пункт меню: ")).strip()

        # --- 1) Последний файл ---
        if choice == "1":
            files = [os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
                     if f.startswith("energy_news") and f.endswith(".json")]
            latest_file = max(files, key=os.path.getctime) if files else None

            if not latest_file:
                print("❗ Нет файлов energy_news*.json")
                continue

            with open(latest_file, "r", encoding="utf-8") as f:
                news_list = json.load(f)
            print(f"📂 Загружено {len(news_list)} новостей из {os.path.basename(latest_file)}")

        # --- 2) Выбранный файл ---
        elif choice == "2":
            file_name = (await asyncio.to_thread(input, "Введите имя файла в папке data/: ")).strip()
            file_path = os.path.join(DATA_DIR, file_name)
            if not os.path.exists(file_path):
                print("❗ Файл не найден")
                continue
            with open(file_path, "r", encoding="utf-8") as f:
                news_list = json.load(f)
            print(f"📂 Загружено {len(news_list)} новостей из {file_name}")

        # --- 3) Количество новостей ---
        elif choice == "3":
            print(f"📊 В базе {len(db.news_db)} новостей.")
            continue

        # --- 4) Очистка базы ---
        elif choice == "4":
            db.news_db.clear()
            db.sent_ids.clear()
            db.save_db()
            db.save_sent_ids()
            print("🗑️ NEWS_DB и sent_ids.json очищены.")
            continue

        # --- 0) Выход ---
        elif choice == "0":
            print("👋 Выход из режима загрузки новостей.")
            break
        else:
            print("❌ Неверный выбор. Попробуйте снова.")
            continue

        # --- Отправка новостей в модерацию ---
        count = 0
        for i, item in enumerate(news_list):
            if not all(k in item for k in ["title", "source", "date", "url", "preview", "full_text"]):
                print(f"⚠️ Пропущена новость #{i} — не хватает ключей")
                continue

            item_id = make_news_id(item, i)
            if item_id in db.sent_ids:
                print(f"⏩ Новость {item_id} уже была отправлена ранее, пропускаем")
                continue

            item["id"] = item_id
            print(f"📨 Отправляем новость {item_id} в канал модерации...")
            await send_to_moderation(bot, item, db)
            count += 1

        print(f"✅ Всего отправлено в модерацию: {count} новых новостей.")
