# parser/html_parser_custom.py
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from parser.utils import clean_text
from parser.nlp_filter import is_energy_related

def parse_eenergy_media():
    url = "https://eenergy.media/rubric/news"
    news_list = []

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        articles = soup.select("div.t-news__item")  # CSS селектор для блоков новостей

        for a in articles:
            title_tag = a.select_one("a.t-news__title")
            if not title_tag:
                continue
            title = clean_text(title_tag.get_text())
            link = title_tag.get("href")
            preview = clean_text(a.select_one("div.t-news__preview").get_text()) if a.select_one("div.t-news__preview") else ""
            date_str = a.select_one("time")["datetime"] if a.select_one("time") else ""
            date = date_str[:16] if date_str else datetime.now().strftime("%Y-%m-%d %H:%M")

            relevant, reason = is_energy_related(title + " " + preview)
            if relevant:
                news_list.append({
                    "title": title,
                    "url": link,
                    "date": date,
                    "source": "E-Energy",
                    "preview": preview[:300] + "...",
                    "full_text": "",
                    "relevance_reason": reason,
                })
    except Exception as e:
        print(f"Ошибка парсинга E-Energy: {e}")

    return news_list


def parse_in_power():
    url = "https://www.in-power.ru/news/alternativnayaenergetika"
    news_list = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        articles = soup.select("div.news-list-item")

        for a in articles:
            title_tag = a.select_one("a.news-title")
            if not title_tag:
                continue
            title = clean_text(title_tag.get_text())
            link = title_tag.get("href")
            preview = clean_text(a.select_one("div.news-text").get_text()) if a.select_one("div.news-text") else ""
            date_tag = a.select_one("div.news-date")
            date = clean_text(date_tag.get_text()) if date_tag else datetime.now().strftime("%Y-%m-%d %H:%M")

            relevant, reason = is_energy_related(title + " " + preview)
            if relevant:
                news_list.append({
                    "title": title,
                    "url": link,
                    "date": date,
                    "source": "In-Power",
                    "preview": preview[:300] + "...",
                    "full_text": "",
                    "relevance_reason": reason,
                })
    except Exception as e:
        print(f"Ошибка парсинга In-Power: {e}")

    return news_list


def parse_neftegaz():
    url = "https://neftegaz.ru/news/Alternative-energy/"
    news_list = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        articles = soup.select("div.article-preview")

        for a in articles:
            title_tag = a.select_one("a.article-title")
            if not title_tag:
                continue
            title = clean_text(title_tag.get_text())
            link = title_tag.get("href")
            preview = clean_text(a.select_one("div.article-text").get_text()) if a.select_one("div.article-text") else ""
            date_tag = a.select_one("div.article-date")
            date = clean_text(date_tag.get_text()) if date_tag else datetime.now().strftime("%Y-%m-%d %H:%M")

            relevant, reason = is_energy_related(title + " " + preview)
            if relevant:
                news_list.append({
                    "title": title,
                    "url": link,
                    "date": date,
                    "source": "Neftegaz",
                    "preview": preview[:300] + "...",
                    "full_text": "",
                    "relevance_reason": reason,
                })
    except Exception as e:
        print(f"Ошибка парсинга Neftegaz: {e}")

    return news_list


def parse_oilcapital():
    url = "https://oilcapital.ru/tags/vie"
    news_list = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        articles = soup.select("div.news-item")

        for a in articles:
            title_tag = a.select_one("a.title")
            if not title_tag:
                continue
            title = clean_text(title_tag.get_text())
            link = title_tag.get("href")
            preview = clean_text(a.select_one("div.preview").get_text()) if a.select_one("div.preview") else ""
            date_tag = a.select_one("span.date")
            date = clean_text(date_tag.get_text()) if date_tag else datetime.now().strftime("%Y-%m-%d %H:%M")

            relevant, reason = is_energy_related(title + " " + preview)
            if relevant:
                news_list.append({
                    "title": title,
                    "url": link,
                    "date": date,
                    "source": "Oilcapital",
                    "preview": preview[:300] + "...",
                    "full_text": "",
                    "relevance_reason": reason,
                })
    except Exception as e:
        print(f"Ошибка парсинга Oilcapital: {e}")

    return news_list


def parse_all_custom_sites():
    all_news = []
    all_news.extend(parse_eenergy_media())
    all_news.extend(parse_in_power())
    all_news.extend(parse_neftegaz())
    all_news.extend(parse_oilcapital())
    return all_news
