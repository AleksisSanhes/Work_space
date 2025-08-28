# bot/formatters.py
import re
import html

def safe_clean_text(text: str) -> str:
    """
    Очищает текст от HTML-тегов, лишних пробелов и спецсимволов.
    """
    if not text:
        return ""
    # Удаляем HTML теги
    text = re.sub(r"<[^>]+>", "", text)
    # Раскодируем HTML сущности
    text = html.unescape(text)
    # Заменяем множественные пробелы на один
    text = re.sub(r"\s+", " ", text).strip()
    return text


def format_news_for_publication(news_item: dict, max_length: int = 3800) -> str:
    """
    Форматирует новость для публикации в канал Telegram.
    """
    title = safe_clean_text(news_item.get("title", "Без заголовка"))
    text = safe_clean_text(news_item.get("full_text", ""))
    source = safe_clean_text(news_item.get("source", "Источник не указан"))
    url = news_item.get("url", "")

    if len(text) > max_length:
        text = text[:max_length] + "... [обрезано]"

    return f"🔥 {title}\n\n{text}\n\nИсточник: {source}\nОригинал: {url}"
