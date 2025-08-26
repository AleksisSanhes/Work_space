# parser/logger_monitor.py
import logging
import sys
import time
from functools import wraps
from tqdm import tqdm
import parser.rss_parser as rss
import parser.nlp_filter as nlp

# --- Настройка логирования ---
def setup_logger(name="parser_monitor", log_file="data/parser_monitor.log", level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    )

    # Вывод в консоль
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Вывод в файл
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger

logger = setup_logger()

# --- Декоратор для замера времени функций ---
def log_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        logger.info(f"START: {func.__name__}")
        result = func(*args, **kwargs)
        end = time.time()
        logger.info(f"END: {func.__name__} | duration: {end-start:.2f} sec")
        return result
    return wrapper

# --- Обёртка для get_full_text ---
def monitored_get_full_text(func):
    @wraps(func)
    def wrapper(url, *args, **kwargs):
        logger.info(f"Fetching full text: {url}")
        start = time.time()
        text = func(url, *args, **kwargs)
        duration = time.time() - start
        logger.info(f"Fetched {len(text)} chars | duration: {duration:.2f} sec")
        return text
    return wrapper

# --- Обёртка для классификации ---
def monitored_is_energy_related(func):
    @wraps(func)
    def wrapper(text, classifier=None, *args, **kwargs):
        start = time.time()
        relevant, reason = func(text, classifier, *args, **kwargs)
        duration = time.time() - start
        logger.info(f"Classification: relevant={relevant} | reason={reason} | duration={duration:.2f} sec")
        return relevant, reason
    return wrapper

# logger_monitor.py (только исправленная обёртка для parse_all_feeds)
def monitored_parse_all_feeds(func):
    @wraps(func)
    def wrapper(classifier=None, stats=None, *args, **kwargs):
        from tqdm import tqdm
        # Оборачиваем RSS_FEEDS в tqdm
        rss.RSS_FEEDS = list(tqdm(rss.RSS_FEEDS, desc="RSS Feeds"))
        logger.info("Starting parse_all_feeds")
        all_news = func(classifier=classifier, stats=stats, *args, **kwargs)
        logger.info(f"Finished parse_all_feeds | total news: {len(all_news)}")
        return all_news
    return wrapper


# --- Применяем обёртки ---
rss.get_full_text = monitored_get_full_text(rss.get_full_text)
nlp.is_energy_related = monitored_is_energy_related(nlp.is_energy_related)
rss.parse_all_feeds = monitored_parse_all_feeds(rss.parse_all_feeds)
