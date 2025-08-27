import requests
from bs4 import BeautifulSoup
from datetime import datetime
from parser.utils import clean_text
from parser.nlp_filter import is_energy_related
import logging
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Сессия с retry
def create_session():
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=[500,502,503,504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

session = create_session()
HEADERS = {"User-Agent": "Mozilla/5.0"}

def parse_site(url, article_selector, title_selector, preview_selector=None, date_selector=None, source_name="Unknown"):
    news_list = []
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        articles = soup.select(article_selector)

        for a in articles:
            title_tag = a.select_one(title_selector)
            if not title_tag:
                continue
            title = clean_text(title_tag.get_text())
            link = title_tag.get("href")
            preview = clean_text(a.select_one(preview_selector).get_text()) if preview_selector and a.select_one(preview_selector) else ""
            date_tag = a.select_one(date_selector) if date_selector else None
            date_str = date_tag.get("datetime") if date_tag and date_tag.has_attr("datetime") else date_tag.get_text() if date_tag else ""
            date = date_str[:16] if date_str else datetime.now().strftime("%Y-%m-%d %H:%M")

            relevant, reason = is_energy_related(title + " " + preview)
            if relevant:
                news_list.append({
                    "title": title,
                    "url": link,
                    "date": date,
                    "source": source_name,
                    "preview": preview[:300] + "...",
                    "full_text": "",
                    "relevance_reason": reason,
                })
    except requests.RequestException as e:
        logger.error(f"Ошибка запроса {source_name}: {e}")
    except Exception as e:
        logger.error(f"Ошибка парсинга {source_name}: {e}")
    return news_list

def parse_eenergy_media():
    return parse_site(
        "https://eenergy.media/rubric/news",
        "div.t-news__item",
        "a.t-news__title",
        "div.t-news__preview",
        "time",
        "E-Energy"
    )

def parse_in_power():
    return parse_site(
        "https://www.in-power.ru/news/alternativnayaenergetika",
        "div.news-list-item",
        "a.news-title",
        "div.news-text",
        "div.news-date",
        "In-Power"
    )

def parse_neftegaz():
    return parse_site(
        "https://neftegaz.ru/news/Alternative-energy/",
        "div.article-preview",
        "a.article-title",
        "div.article-text",
        "div.article-date",
        "Neftegaz"
    )

def parse_oilcapital():
    return parse_site(
        "https://oilcapital.ru/tags/vie",
        "div.news-item",
        "a.title",
        "div.preview",
        "span.date",
        "Oilcapital"
    )

def parse_all_custom_sites():
    all_news = []
    all_news.extend(parse_eenergy_media())
    all_news.extend(parse_in_power())
    all_news.extend(parse_neftegaz())
    all_news.extend(parse_oilcapital())
    return all_news
