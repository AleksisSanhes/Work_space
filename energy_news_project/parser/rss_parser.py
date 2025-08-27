import feedparser
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from parser.utils import clean_text
from parser.nlp_filter import is_energy_related
from parser.stats import update_stats
import logging
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    {"url": "https://lenta.ru/rss/news", "name": "Lenta.ru"},
    {"url": "https://www.interfax.ru/rss.asp", "name": "Interfax"},
    {"url": "https://ria.ru/export/rss2/archive/index.xml", "name": "RIA Novosti"},
    {"url": "https://www.vedomosti.ru/rss/news", "name": "Vedomosti"},
    {"url": "https://hightech.fm/feed", "name": "Hi-Tech Mail.ru"},
    # {"url": "https://recyclemag.ru/rss.xml", "name": "Recyclemag"}, # don't work
    # {"url": "https://www.kommersant.ru/RSS/news/energy", "name": "Коммерсантъ Энергетика"}, # don't work
    # {"url": "https://tass.ru/rss/economy.xml", "name": "ТАСС Экономика"}, # don't work
    # {"url": "https://ria.ru/export/rss2/tech/index.xml", "name": "РИА Наука"}, # don't work
    # {"url": "http://energosovet.ru/rss.xml", "name": "Энергосовет"}, # don't work
    {"url": "https://renen.ru/feed/", "name": "RENEN - ВИЭ"},
    # {"url": "https://greenevolution.ru/feed/", "name": "Green Evolution"}, # don't work
    {"url": "https://energovector.com/feed/", "name": "Энерговектор"},
    # {"url": "https://www.reutersagency.com/feed/?best-topics=energy&post_type=best", "name": "Reuters Energy"}, # don't work
    # {"url": "https://www.bloomberg.com/feeds/bbiz/sustainability.xml", "name": "Bloomberg Green"}, # don't work
    {"url": "https://cleantechnica.com/feed/", "name": "CleanTechnica"},
    {"url": "https://www.h2-view.com/feed/", "name": "H2 View"},
    {"url": "https://energynews.us/feed/", "name": "Energy News Network"},
    {"url": "https://www.greentechmedia.com/feed", "name": "Greentech Media"},
    {"url": "https://www.hydrogenfuelnews.com/feed/", "name": "Hydrogen Fuel News"},
    {"url": "https://www.pv-magazine.com/feed/", "name": "PV Magazine"},
    {"url": "https://www.renewableenergyworld.com/feed/", "name": "Renewable Energy World"},
    # {"url": "https://www.greencarcongress.com/index.xml", "name": "Green Car Congress"}, # не работает
    {"url": "https://www.energy-storage.news/feed/", "name": "Energy Storage News"},
    {"url": "https://eenergy.media/rubric/news/feed", "name": "E-Energy"}, # работает
    # {"url": "https://www.in-power.ru/news/alternativnayaenergetika", "name": "In-Power"}, # не работает
    # {"url": "https://neftegaz.ru/news/Alternative-energy", "name": "Neftegaz"}, # не работает
    {"url": "https://oilcapital.ru/rss", "name": "Oilcapital"}, # работает
    {"url": "https://renen.ru/feed", "name": "renen"}, # работает
]

# Сессия с retry
session = requests.Session()
retry = Retry(total=5, backoff_factor=0.5, status_forcelist=[500,502,503,504], allowed_methods=["GET"])
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)
HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_full_text(url):
    base_url = url.split('?')[0]
    try:
        response = session.get(base_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
        text = " ".join([p.get_text(strip=True) for p in soup.select("p") if len(p.get_text(strip=True)) > 30])
        return clean_text(text)
    except requests.ConnectionError as e:
        logger.warning(f"Connection error {url}: {e}")
        return ""
    except requests.RequestException as e:
        logger.warning(f"Request error {url}: {e}")
        return ""
    except Exception as e:
        logger.warning(f"Unexpected error {url}: {e}")
        return ""

def parse_feed(feed_url, source_name, classifier, stats):
    results = []
    three_weeks_ago = datetime.now() - timedelta(days=21)
    try:
        response = session.get(feed_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        logger.error(f"Ошибка запроса RSS {feed_url}: {e}")
        update_stats(stats, source_name, "failed_request")
        return results

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
