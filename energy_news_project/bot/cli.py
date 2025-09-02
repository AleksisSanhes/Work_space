import os
import json
import asyncio
from bot.db import NewsDB
from bot.telegram_bot import send_to_moderation, make_news_id

DATA_DIR = "data"


async def safe_input(prompt):
    """Безопасный ввод с обработкой кодировки"""
    try:
        return (await asyncio.to_thread(input, prompt)).strip()
    except UnicodeDecodeError:
        print("⚠️ Ошибка кодировки. Попробуйте еще раз.")
        return ""
    except Exception as e:
        print(f"⚠️ Ошибка ввода: {e}")
        return ""


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
        print("5) Очистить поврежденные записи (без message_id)")
        print("0) Выход")

        choice = await safe_input("Введите пункт меню: ")

        if not choice:  # Если ввод пустой из-за ошибки
            continue

        # --- 1) Последний файл ---
        if choice == "1":
            files = [os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
                     if f.startswith("energy_news") and f.endswith(".json")]
            latest_file = max(files, key=os.path.getctime) if files else None

            if not latest_file:
                print("❗ Нет файлов energy_news*.json")
                continue

            try:
                with open(latest_file, "r", encoding="utf-8") as f:
                    news_list = json.load(f)
                print(f"📂 Загружено {len(news_list)} новостей из {os.path.basename(latest_file)}")
            except Exception as e:
                print(f"❗ Ошибка чтения файла {latest_file}: {e}")
                continue

        # --- 2) Выбранный файл ---
        elif choice == "2":
            file_name = await safe_input("Введите имя файла в папке data/: ")
            if not file_name:
                continue

            file_path = os.path.join(DATA_DIR, file_name)
            if not os.path.exists(file_path):
                print("❗ Файл не найден")
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    news_list = json.load(f)
                print(f"📂 Загружено {len(news_list)} новостей из {file_name}")
            except Exception as e:
                print(f"❗ Ошибка чтения файла {file_path}: {e}")
                continue

        # --- 3) Количество новостей ---
        elif choice == "3":
            print(f"📊 В базе {len(db.news_db)} новостей.")
            continue

        # --- 4) Очистка базы ---
        elif choice == "4":
            confirm = await safe_input("Вы уверены, что хотите очистить базу? (yes/no): ")
            if confirm.lower() in ['yes', 'y', 'да', 'д']:
                db.news_db.clear()
                db.sent_ids.clear()
                db.save_db()
                db.save_sent_ids()
                print("🗑️ NEWS_DB и sent_ids.json очищены.")
            else:
                print("❌ Очистка отменена.")
            continue

        # --- 5) Очистка поврежденных записей ---
        elif choice == "5":
            broken_count = 0
            for news_id, data in list(db.news_db.items()):
                if data.get("message_id") is None:
                    db.delete_news(news_id)
                    broken_count += 1
            print(f"🔧 Удалено {broken_count} записей с поврежденными message_id.")
            continue

        # --- 0) Выход ---
        elif choice == "0":
            print("👋 Выход из режима загрузки новостей.")
            break
        else:
            print("❌ Неверный выбор. Попробуйте снова.")
            continue

        # --- Отправка новостей в модерацию ---
        if 'news_list' in locals():
            count = 0
            failed_count = 0

            for i, item in enumerate(news_list):
                if not all(k in item for k in ["title", "source", "date", "url", "preview", "full_text"]):
                    print(f"⚠️ Пропущена новость #{i} — не хватает ключей")
                    failed_count += 1
                    continue

                try:
                    item_id = make_news_id(item, i)
                    if item_id in db.sent_ids:
                        print(f"⏩ Новость {item_id} уже была отправлена ранее, пропускаем")
                        continue

                    item["id"] = item_id
                    print(f"📨 Отправляем новость {item_id} в канал модерации...")
                    await send_to_moderation(bot, item, db)
                    count += 1

                    # Небольшая задержка между отправками
                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"❗ Ошибка отправки новости #{i}: {e}")
                    failed_count += 1

            print(f"✅ Всего отправлено в модерацию: {count} новых новостей.")
            if failed_count > 0:
                print(f"⚠️ Не удалось обработать: {failed_count} новостей.")

            # Очищаем переменную для следующей итерации
            del news_list