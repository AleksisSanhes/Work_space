import re
import html

def safe_clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def format_news_for_publication(news_item: dict) -> str:
    title = safe_clean_text(news_item.get("title", "Без заголовка"))
    text = safe_clean_text(news_item.get("full_text", ""))
    source = safe_clean_text(news_item.get("source", "Источник не указан"))
    url = news_item.get("url", "")

    if len(text) > 3800:
        text = text[:3800] + "... [обрезано]"

    return f"🔥 {title}\n\n{text}\n\nИсточник: {source}\nОригинал: {url}"
