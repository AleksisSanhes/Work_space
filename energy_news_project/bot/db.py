import json
import os

SENT_IDS_FILE = "data/sent_ids.json"
NEWS_DB_FILE = "data/news_db.json"

NEWS_DB = {}

def load_sent_ids() -> set:
    if os.path.exists(SENT_IDS_FILE):
        with open(SENT_IDS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_sent_ids(sent_ids: set):
    with open(SENT_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_ids), f, ensure_ascii=False)

def load_news_db():
    global NEWS_DB
    if os.path.exists(NEWS_DB_FILE):
        with open(NEWS_DB_FILE, "r", encoding="utf-8") as f:
            NEWS_DB = json.load(f)

def save_news_db():
    with open(NEWS_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(NEWS_DB, f, ensure_ascii=False)
