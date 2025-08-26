import feedparser
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

from .utils import clean_text
from .nlp_filter import is_energy_related, translate_text
from .stats import update_stats
#
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
    {"url": "https://www.energy-storage.news/feed/", "name": "Energy Storage News"},
    {"url": "https://eenergy.media/rubric/news", "name": "E-Energy"},
    {"url": "https://www.in-power.ru/news/alternativnayaenergetika", "name": "In-Power"},
    {"url": "https://neftegaz.ru/news/Alternative-energy/", "name": "Neftegaz"},
    {"url": "https://oilcapital.ru/rss", "name": "Oilcapital"},
]

def get_full_text(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        text = " ".join([p.get_text(strip=True) for p in soup.select("p") if len(p.get_text(strip=True)) > 30])
        return clean_text(text)
    except Exception:
        return ""

def parse_feed(feed_url, source_name, classifier, stats):
    results = []
    headers = {"User-Agent": "Mozilla/5.0"}
    three_weeks_ago = datetime.now() - timedelta(days=21)

    response = requests.get(feed_url, headers=headers, timeout=20)
    feed = feedparser.parse(response.text)

    for entry in feed.entries:
        pub_date = datetime.now()
        if hasattr(entry, "published_parsed"):
            pub_date = datetime(*entry.published_parsed[:6])

        if pub_date < three_weeks_ago:
            update_stats(stats, source_name, "old_date")
            continue

        content = entry.title + " " + getattr(entry, "summary", "")
        full_text = get_full_text(entry.link)
        combined_text = content + " " + full_text

        relevant, reason = is_energy_related(combined_text, classifier)
        if relevant:
            news = {
                "title": entry.title,
                "url": entry.link,
                "date": pub_date.strftime("%Y-%m-%d %H:%M"),
                "source": source_name,
                "preview": combined_text[:300] + "...",
                "full_text": full_text,
                "relevance_reason": reason,
            }
            results.append(news)
            update_stats(stats, source_name, "accepted")
        else:
            update_stats(stats, source_name, "not_relevant")

    return results

def parse_all_feeds(classifier=None, stats=None):
    all_news = []
    for feed in RSS_FEEDS:
        news = parse_feed(feed["url"], feed["name"], classifier, stats)
        all_news.extend(news)
    return all_news
