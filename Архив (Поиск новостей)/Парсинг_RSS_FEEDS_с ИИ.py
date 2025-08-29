import feedparser
from datetime import datetime, timedelta
import requests
import json
from bs4 import BeautifulSoup
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
import re
import logging
import sys
import io
import html
from deep_translator import GoogleTranslator
from collections import defaultdict

# Исправление проблем с кодировкой
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Настройка логгирования с UTF-8
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    file_handler = logging.FileHandler('news_parser.log', encoding='utf-8')
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger

logger = setup_logging()

# RSS источники
RSS_FEEDS = [
    {"url": "https://lenta.ru/rss/news", "name": "Lenta.ru"},
    {"url": "https://www.interfax.ru/rss.asp", "name": "Interfax"},
    {"url": "https://ria.ru/export/rss2/archive/index.xml", "name": "RIA Novosti"},
    {"url": "https://www.vedomosti.ru/rss/news", "name": "Vedomosti"},
    {"url": "https://hightech.fm/feed", "name": "Hi-Tech Mail.ru"},
    {"url": "https://recyclemag.ru/rss.xml", "name": "Recyclemag"},
    {"url": "https://www.kommersant.ru/RSS/news/energy", "name": "Коммерсантъ Энергетика"},
    {"url": "https://tass.ru/rss/economy.xml", "name": "ТАСС Экономика"},
    {"url": "https://ria.ru/export/rss2/tech/index.xml", "name": "РИА Наука"},
    {"url": "http://energosovet.ru/rss.xml", "name": "Энергосовет"},
    {"url": "https://renen.ru/feed/", "name": "RENEN - ВИЭ"},
    {"url": "https://greenevolution.ru/feed/", "name": "Green Evolution"},
    {"url": "https://energovector.com/feed/", "name": "Энерговектор"},
    {"url": "https://www.reutersagency.com/feed/?best-topics=energy&post_type=best", "name": "Reuters Energy"},
    {"url": "https://www.bloomberg.com/feeds/bbiz/sustainability.xml", "name": "Bloomberg Green"},
    {"url": "https://cleantechnica.com/feed/", "name": "CleanTechnica"},
    {"url": "https://www.h2-view.com/feed/", "name": "H2 View"},
    {"url": "https://energynews.us/feed/", "name": "Energy News Network"},
    {"url": "https://www.greentechmedia.com/feed", "name": "Greentech Media"},
    {"url": "https://www.hydrogenfuelnews.com/feed/", "name": "Hydrogen Fuel News"},
    {"url": "https://www.pv-magazine.com/feed/", "name": "PV Magazine"},
    {"url": "https://www.renewableenergyworld.com/feed/", "name": "Renewable Energy World"},
    {"url": "https://www.greencarcongress.com/index.xml", "name": "Green Car Congress"},
    {"url": "https://www.energy-storage.news/feed/", "name": "Energy Storage News"}
]

# Ключевые слова
EXPANDED_KEYWORDS = [
    "энергетик", "виэ", "водород", "акб", "экологи", "декарбонизац", "возобнов", "электромобил",
    "экотех", "климат", "энергопереход", "renewable", "solar", "wind", "battery", "hydrogen",
    "decarbonization", "sustainability", "green energy", "clean tech", "photovoltaic", "wind turbine",
    "энергоэффективность", "биотопливо", "геотермальный", "приливная энергия", "энергосбережение"
]
# Глобальные счетчики статистики
stats = {
    'total_articles': 0,
    'accepted': 0,
    'rejected': defaultdict(int),
    'failed_sources': [],
    'source_details': {}
}
# Загрузка модели
def load_classification_model():
    logger.info("Загрузка модели классификации...")
    try:
        model_name = "cointegrated/rubert-tiny2-cedr-emotion-detection"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        classifier = pipeline(
            "text-classification",
            model=model,
            tokenizer=tokenizer,
            device=0 if torch.cuda.is_available() else -1
        )
        logger.info("Модель загружена")
        return classifier
    except Exception as e:
        logger.error(f"Ошибка загрузки модели: {str(e)}")
        return None

# Проверка релевантности
def is_energy_related(text, classifier=None, threshold=0.90):
    if not text.strip():
        return False, "Пустой текст"
    text_lower = text.lower()
    keyword_count = sum(1 for keyword in EXPANDED_KEYWORDS if keyword.lower() in text_lower)
    if keyword_count >= 2:
        return True, f"Найдено {keyword_count} ключевых слов"
    if not classifier:
        return keyword_count > 0, "Проверка только по ключевым словам"
    try:
        result = classifier(text[:400], truncation=True, max_length=512)
        for res in result:
            if res['label'] == 'neutral' and res['score'] > threshold:
                return True, f"ИИ-классификация ({res['score']:.2f})"
        return False, "Нерелевантно"
    except Exception as e:
        logger.error(f"Ошибка классификации: {str(e)}")
        return keyword_count > 0, "Ошибка ИИ"

# Очистка текста
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return html.unescape(text)

# Получение полного текста с обновленной статистикой
def get_full_text(url, headers, source_name):
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        text = ' '.join([p.get_text(strip=True) for p in soup.select('p') if len(p.get_text(strip=True)) > 30])
        return clean_text(text)
    except Exception as e:
        logger.warning(f"Ошибка получения полного текста ({source_name} - {url}): {str(e)}")
        stats['rejected']['parse_error'] += 1
        return ""

# Перевод
def translate_text(text, src='en', dest='ru', source_name=None, article_url=None):
    if not text.strip():
        return text

    try:
        max_chunk_size = 4500
        chunks = [text[i:i + max_chunk_size] for i in range(0, len(text), max_chunk_size)]
        translated_chunks = []

        for chunk in chunks:
            translated = GoogleTranslator(source=src, target=dest).translate(chunk)
            translated_chunks.append(translated)

        return " ".join(translated_chunks)
    except Exception as e:
        logger.warning(
            f"Ошибка перевода ({source_name or 'неизвестный источник'} - {article_url or 'нет ссылки'}): {str(e)}"
        )
        return text


# Парсинг RSS с добавлением статистики
def parse_rss_feed(feed_url, source_name, classifier=None):
    source_stats = {
        'total': 0,
        'accepted': 0,
        'rejected': defaultdict(int),
        'errors': []
    }
    results = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    three_weeks_ago = datetime.now() - timedelta(days=21)

    try:
        response = requests.get(feed_url, headers=headers, timeout=20)
    except requests.exceptions.RequestException as e:
        error_msg = f"Ошибка подключения: {str(e)}"
        logger.warning(error_msg)
        stats['failed_sources'].append(source_name)
        source_stats['errors'].append(error_msg)
        return results, source_stats

    feed = feedparser.parse(response.text)

    for entry in feed.entries:
        source_stats['total'] += 1
        stats['total_articles'] += 1

        try:
            pub_date = datetime.now()
            if hasattr(entry, 'published_parsed'):
                pub_date = datetime(*entry.published_parsed[:6])

            # Проверка даты
            if pub_date < three_weeks_ago:
                source_stats['rejected']['old_date'] += 1
                stats['rejected']['old_date'] += 1
                continue

            content = entry.title + " " + getattr(entry, 'summary', "")
            full_text = get_full_text(entry.link, headers, source_name)
            combined_text = content + " " + full_text

            # Проверка пустого контента
            if not combined_text.strip():
                source_stats['rejected']['empty_content'] += 1
                stats['rejected']['empty_content'] += 1
                continue

            # Определение языка
            is_english = any(domain in entry.link.lower() for domain in [
                'reuters', 'bloomberg', 'cleantechnica', 'h2-view',
                'greentechmedia', 'hydrogenfuelnews', 'pv-magazine',
                'renewableenergyworld', 'greencarcongress', 'energy-storage'
            ])

            # Перевод при необходимости
            if is_english:
                combined_text_ru = translate_text(combined_text, source_name=source_name, article_url=entry.link)
                title_ru = translate_text(entry.title, source_name=source_name, article_url=entry.link)
                full_text_ru = translate_text(full_text, source_name=source_name, article_url=entry.link)
            else:
                combined_text_ru = combined_text
                title_ru = entry.title
                full_text_ru = full_text

            # Проверка релевантности
            relevant, reason = is_energy_related(combined_text_ru, classifier)
            if relevant:
                results.append({
                    "title": title_ru,
                    "url": entry.link,
                    "date": pub_date.strftime("%Y-%m-%d %H:%M"),
                    "source": source_name,
                    "preview": combined_text_ru[:300] + "...",
                    "full_text": full_text_ru,
                    "relevance_reason": reason,
                    "language": "ru"
                })
                source_stats['accepted'] += 1
                stats['accepted'] += 1
            else:
                source_stats['rejected']['not_relevant'] += 1
                stats['rejected']['not_relevant'] += 1

        except Exception as e:
            error_msg = f"Ошибка обработки: {str(e)}"
            logger.error(error_msg, exc_info=True)
            source_stats['rejected']['processing_error'] += 1
            stats['rejected']['processing_error'] += 1
            source_stats['errors'].append(error_msg)

    return results, source_stats


# Генерация отчета о статистике
def generate_stats_report():
    report = "\n===== СТАТИСТИКА ОБРАБОТКИ =====\n"
    report += f"Всего источников: {len(RSS_FEEDS)}\n"
    report += f"Успешно обработано: {len(RSS_FEEDS) - len(stats['failed_sources'])}\n"
    report += f"Не удалось обработать: {len(stats['failed_sources'])}"

    if stats['failed_sources']:
        report += f" ({', '.join(stats['failed_sources'])}"

    report += f"\n\nВсего статей: {stats['total_articles']}"
    report += f"\nПринято статей: {stats['accepted']}"
    report += f"\nОтклонено статей: {stats['total_articles'] - stats['accepted']}"

    if stats['rejected']:
        report += "\n\nПричины отклонения:"
        for reason, count in stats['rejected'].items():
            reason_name = {
                'old_date': 'Устаревшие (старше 3 недель)',
                'empty_content': 'Пустой контент',
                'not_relevant': 'Нерелевантные',
                'parse_error': 'Ошибки парсинга',
                'processing_error': 'Ошибки обработки'
            }.get(reason, reason)
            report += f"\n  - {reason_name}: {count}"

    report += "\n\nДЕТАЛИ ПО ИСТОЧНИКАМ:\n"
    for source, data in stats['source_details'].items():
        report += f"\n* {source}:"
        report += f"\n  Всего статей: {data['total']}"
        report += f"\n  Принято: {data['accepted']}"
        report += f"\n  Отклонено: {data['total'] - data['accepted']}"
        if data['rejected']:
            for reason, count in data['rejected'].items():
                reason_name = {
                    'old_date': 'Устаревшие',
                    'empty_content': 'Пустой контент',
                    'not_relevant': 'Нерелевантные',
                    'parse_error': 'Ошибки парсинга',
                    'processing_error': 'Ошибки обработки'
                }.get(reason, reason)
                report += f"\n    - {reason_name}: {count}"
        if data['errors']:
            report += f"\n  Ошибки: {len(data['errors'])}"

    report += "\n\n===== АНАЛИЗ РЕЗУЛЬТАТОВ =====\n"
    report += f"Эффективность отбора: {stats['accepted'] / stats['total_articles']:.1%}" if stats[
        'total_articles'] else "Нет данных"
    report += f"\nОсновная причина отклонений: {max(stats['rejected'], key=stats['rejected'].get, default='N/A')}"
    report += "\n\nРекомендации:"

    if stats['rejected'].get('parse_error', 0) > 3:
        report += "\n- Проверить проблемные источники с ошибками парсинга"
    if stats['rejected'].get('not_relevant', 0) / stats['total_articles'] > 0.5:
        report += "\n- Уточнить ключевые слова для улучшения релевантности"
    if not stats['accepted']:
        report += "\n- Проверить работоспособность системы классификации"

    return report


# Основной блок с обработкой статистики
if __name__ == "__main__":
    classifier = load_classification_model()
    all_news = []
    stats['start_time'] = datetime.now()

    for feed in RSS_FEEDS:
        logger.info(f"Обработка {feed['name']}")
        news, source_stats = parse_rss_feed(feed['url'], feed['name'], classifier)
        all_news.extend(news)
        stats['source_details'][feed['name']] = source_stats

    stats['end_time'] = datetime.now()
    stats['processing_time'] = str(stats['end_time'] - stats['start_time'])

    if all_news:
        # Генерация имен файлов с timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        json_filename = f'energy_news_{timestamp}.json'
        txt_filename = f'energy_news_{timestamp}.txt'
        stats_filename = f'processing_stats_{timestamp}.txt'

        # Сохранение новостей в JSON
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(all_news, f, indent=2, ensure_ascii=False)

        # Сохранение полного отчета
        report = generate_stats_report()
        with open(stats_filename, 'w', encoding='utf-8') as f:
            f.write(report)

        # Сохранение новостей и статистики в единый TXT
        with open(txt_filename, 'w', encoding='utf-8') as f:
            f.write(report + "\n\n")
            f.write("=" * 80 + "\n")
            f.write(f"СОБРАННЫЕ НОВОСТИ ({len(all_news)} шт)\n")
            f.write("=" * 80 + "\n\n")

            for i, news in enumerate(all_news, 1):
                f.write(f"{i}. [{news['source']}] {news['title']}\n")
                f.write(f"Дата: {news['date']}\n")
                f.write(f"Ссылка: {news['url']}\n")
                f.write(f"Предпросмотр: {news['preview']}\n")
                f.write(f"Причина отбора: {news['relevance_reason']}\n")
                f.write("-" * 80 + "\n")

        logger.info(f"Сохранено {len(all_news)} новостей")
        logger.info(f"Отчет о статистике сохранен в {stats_filename}")
        print(report)  # Вывод статистики в консоль
    else:
        logger.warning("Новости не найдены")
        print(generate_stats_report())


# В основной блок после сохранения JSON
import subprocess

# Добавляем ID к каждой новости
for i, news_item in enumerate(all_news):
    news_item['id'] = f"{timestamp}_{i}"

# Перезаписываем файл с ID
with open(json_filename, 'w', encoding='utf-8') as f:
    json.dump(all_news, f, indent=2, ensure_ascii=False)

# Запускаем бота после завершения парсинга
subprocess.Popen(["python", "bot.py"])