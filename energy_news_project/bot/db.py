# bot/db.py
import json
import os

class NewsDB:
    def __init__(self, db_file="data/news_db.json", sent_ids_file="data/sent_ids.json"):
        self.db_file = db_file
        self.sent_ids_file = sent_ids_file
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.sent_ids_file), exist_ok=True)
        self.news_db = {}   # {news_id: {...}}
        self.sent_ids = set()
        self.load_db()
        self.load_sent_ids()

    def load_db(self):
        if os.path.exists(self.db_file):
            with open(self.db_file, "r", encoding="utf-8") as f:
                self.news_db = json.load(f)

    def save_db(self):
        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump(self.news_db, f, ensure_ascii=False)

    def load_sent_ids(self):
        if os.path.exists(self.sent_ids_file):
            with open(self.sent_ids_file, "r", encoding="utf-8") as f:
                self.sent_ids = set(json.load(f))

    def save_sent_ids(self):
        with open(self.sent_ids_file, "w", encoding="utf-8") as f:
            json.dump(list(self.sent_ids), f, ensure_ascii=False)

    # --- Утилиты для работы с БД ---
    def add_news(self, news_id, news_data, message_id, channel_id):
        self.news_db[news_id] = {
            "news_data": news_data,
            "message_id": message_id,
            "channel_id": channel_id
        }
        self.sent_ids.add(news_id)
        self.save_db()
        self.save_sent_ids()

    def get_news(self, news_id):
        return self.news_db.get(news_id)

    def delete_news(self, news_id):
        if news_id in self.news_db:
            del self.news_db[news_id]
            self.sent_ids.discard(news_id)
            self.save_db()
            self.save_sent_ids()
