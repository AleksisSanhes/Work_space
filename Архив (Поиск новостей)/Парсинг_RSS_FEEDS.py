import feedparser
from datetime import datetime, timedelta
import requests
import json
from bs4 import BeautifulSoup

# Рабочие альтернативные RSS-источники
RSS_FEEDS = [
    {"url": "https://lenta.ru/rss/news", "name": "Lenta.ru"},
    {"url": "https://www.interfax.ru/rss.asp", "name": "Interfax"},
    {"url": "https://ria.ru/export/rss2/archive/index.xml", "name": "RIA Novosti"},
    {"url": "https://www.vedomosti.ru/rss/news", "name": "Vedomosti"},
    {"url": "https://hightech.fm/feed", "name": "Hi-Tech Mail.ru"},  # Технологии и инновации
    {"url": "https://recyclemag.ru/rss.xml", "name": "Recyclemag"}  # Экология и ВИЭ
]

KEYWORDS = ["энергетик", "виэ", "водород", "акб", "экологи", "декарбонизац",
            "возобнов", "электромобил", "экотех", "климат", "энергопереход",
            "renewable", "solar", "wind", "battery", "hydrogen", "decarbonization"]


def parse_rss_feed(feed_url, source_name):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(feed_url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        feed = feedparser.parse(response.text)

        results = []
        three_weeks_ago = datetime.now() - timedelta(days=21)

        for entry in feed.entries:
            # Обработка даты
            if hasattr(entry, 'published_parsed'):
                pub_date = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, 'updated_parsed'):
                pub_date = datetime(*entry.updated_parsed[:6])
            else:
                pub_date = datetime.now()

            if pub_date < three_weeks_ago:
                continue

            # Сбор контента для анализа
            content = ""
            if hasattr(entry, 'title'):
                content += entry.title.lower() + " "
            if hasattr(entry, 'summary'):
                content += entry.summary.lower() + " "
            if hasattr(entry, 'description'):
                content += entry.description.lower() + " "

            # Проверка на ключевые слова
            if any(keyword in content for keyword in KEYWORDS):
                # Получение полного текста для некоторых источников
                full_text = ""
                if 'ria.ru' in feed_url or 'hightech.fm' in feed_url:
                    try:
                        article_resp = requests.get(entry.link, headers=headers, timeout=5)
                        soup = BeautifulSoup(article_resp.text, 'html.parser')

                        if 'ria.ru' in feed_url:
                            article_div = soup.find('div', class_='article__text')
                            if article_div:
                                full_text = article_div.get_text(separator=' ', strip=True)[:500] + "..."
                        elif 'hightech.fm' in feed_url:
                            article_div = soup.find('div', class_='post__text')
                            if article_div:
                                full_text = article_div.get_text(separator=' ', strip=True)[:500] + "..."
                    except:
                        pass

                results.append({
                    "title": entry.title if hasattr(entry, 'title') else "Без названия",
                    "url": entry.link,
                    "date": pub_date.strftime("%Y-%m-%d %H:%M"),
                    "source": source_name,
                    "preview": content[:200] + "..." if len(content) > 200 else content,
                    "full_text": full_text
                })

        return results

    except Exception as e:
        print(f"Ошибка при обработке {source_name}: {str(e)}")
        return []


# Сбор новостей со всех источников
all_news = []
for feed in RSS_FEEDS:
    print(f"🔎 Проверка: {feed['name']}")
    news = parse_rss_feed(feed['url'], feed['name'])
    all_news.extend(news)
    print(f"   Найдено новостей: {len(news)}")

# Сохранение результатов
with open('energy_news.json', 'w', encoding='utf-8') as f:
    json.dump(all_news, f, indent=2, ensure_ascii=False, default=str)

print(f"\n💾 Всего собрано новостей: {len(all_news)}")
print("Сохранено в energy_news.json")