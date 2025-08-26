# main_parser.py
from parser.rss_parser import parse_all_feeds
from parser.html_parser_custom import parse_all_custom_sites
from parser.stats import init_stats, generate_stats_report, save_results
from parser.nlp_filter import load_classification_model
from parser.logger_monitor import logger
from datetime import datetime

if __name__ == "__main__":
    logger.info("Запуск парсера новостей")

    # --- Инициализация статистики и модели ---
    stats = init_stats()
    classifier = load_classification_model()

    # --- 1) Парсим RSS-фиды ---
    logger.info("Парсинг RSS-фидов")
    rss_news = parse_all_feeds(classifier=classifier, stats=stats)
    logger.info(f"Найдено {len(rss_news)} новостей из RSS")

    # --- 2) Парсим кастомные HTML-сайты ---
    logger.info("Парсинг HTML-сайтов")
    html_news = parse_all_custom_sites()
    logger.info(f"Найдено {len(html_news)} новостей с HTML-сайтов")

    # --- 3) Объединяем все новости ---
    all_news = rss_news + html_news
    logger.info(f"Всего новостей: {len(all_news)}")

    # --- 4) Сохраняем результаты ---
    if all_news:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        json_file, stats_file = save_results(all_news, stats, timestamp)
        logger.info(f"Сохранено {len(all_news)} новостей в {json_file}")
        logger.info(generate_stats_report(stats))
    else:
        logger.info("Новости не найдены")
