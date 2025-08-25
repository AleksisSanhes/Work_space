import json
from collections import defaultdict
from datetime import datetime
import os

def init_stats():
    return {
        "total_articles": 0,
        "accepted": 0,
        "rejected": defaultdict(int),
        "failed_sources": [],
        "source_details": {},
        "start_time": datetime.now()
    }

def update_stats(stats, source, reason):
    source_stats = stats["source_details"].setdefault(
        source, {"total": 0, "accepted": 0, "rejected": defaultdict(int), "errors": []}
    )
    stats["total_articles"] += 1
    source_stats["total"] += 1

    if reason == "accepted":
        stats["accepted"] += 1
        source_stats["accepted"] += 1
    else:
        stats["rejected"][reason] += 1
        source_stats["rejected"][reason] += 1

def generate_stats_report(stats):
    report = "\n===== СТАТИСТИКА ОБРАБОТКИ =====\n"
    report += f"Всего статей: {stats['total_articles']}\n"
    report += f"Принято: {stats['accepted']}\n"
    report += f"Отклонено: {stats['total_articles'] - stats['accepted']}\n"
    return report

def save_results(all_news, stats, timestamp):
    # Создаём папку data, если её нет
    os.makedirs("data", exist_ok=True)

    json_filename = f"data/energy_news_{timestamp}.json"
    stats_filename = f"data/processing_stats_{timestamp}.txt"

    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(all_news, f, indent=2, ensure_ascii=False)

    with open(stats_filename, "w", encoding="utf-8") as f:
        f.write(generate_stats_report(stats))

    return json_filename, stats_filename
