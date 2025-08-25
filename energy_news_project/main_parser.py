from parser.rss_parser import parse_all_feeds
from parser.stats import init_stats, generate_stats_report, save_results
from parser.nlp_filter import load_classification_model
from datetime import datetime

if __name__ == "__main__":
    stats = init_stats()
    classifier = load_classification_model()
    all_news = parse_all_feeds(classifier=classifier, stats=stats)

    if all_news:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        json_file, stats_file = save_results(all_news, stats, timestamp)
        print(f"Сохранено {len(all_news)} новостей в {json_file}")
        print(generate_stats_report(stats))
    else:
        print("Новости не найдены")
