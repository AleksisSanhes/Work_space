from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
import time
import random
import json
from datetime import datetime, timedelta
import re
import os
from webdriver_manager.chrome import ChromeDriverManager


def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(100, 125)}.0.0.0 Safari/537.36")

    # Для работы в headless режиме (раскомментировать для сервера)
    # chrome_options.add_argument("--headless=new")

    # Инициализация драйвера с автоматической установкой
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Скрытие WebDriver признаков
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    return driver


def human_like_interaction(driver):
    """Имитация человеческого поведения"""
    try:
        # Плавная прокрутка страницы
        scroll_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, scroll_height, random.randint(100, 300)):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(random.uniform(0.1, 0.3))

        # Случайные движения мыши
        actions = ActionChains(driver)
        for _ in range(random.randint(2, 5)):
            x_offset = random.randint(-100, 100)
            y_offset = random.randint(-100, 100)
            actions.move_by_offset(x_offset, y_offset).perform()
            time.sleep(random.uniform(0.2, 0.5))

        # Клик в случайное место
        if random.random() > 0.7:
            element = driver.find_element(By.TAG_NAME, 'body')
            actions.move_to_element_with_offset(element, random.randint(10, 100),
                                                random.randint(10, 100)).click().perform()
            time.sleep(random.uniform(0.5, 1.5))
    except:
        pass


def parse_kommersant():
    driver = setup_driver()
    news_items = []
    three_weeks_ago = datetime.now() - timedelta(days=21)

    try:
        # Основной URL раздела "Энергетика"
        base_url = "https://www.kommersant.ru/rubric/3"
        print(f"🛜 Загружаем страницу: {base_url}")
        driver.get(base_url)

        # Ожидание загрузки контента
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article.rubric_lenta__item"))
        )

        # Имитация человеческого поведения
        human_like_interaction(driver)

        # Прокрутка для загрузки всех элементов
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0

        while scroll_attempts < 3:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(1.5, 3.0))
            new_height = driver.execute_script("return document.body.scrollHeight")

            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
                last_height = new_height

            # Дополнительная имитация поведения
            if random.random() > 0.5:
                human_like_interaction(driver)

        # Парсинг списка статей
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        articles = soup.select('article.rubric_lenta__item')
        print(f"🔍 Найдено статей: {len(articles)}")

        # Обработка каждой статьи
        for article in articles:
            try:
                # Извлекаем заголовок и ссылку
                title_tag = article.select_one('a.rubric_lenta__item_link')
                if not title_tag:
                    continue

                title = title_tag.text.strip()
                link = "https://www.kommersant.ru" + title_tag['href']

                # Извлекаем дату
                date_tag = article.select_one('time.uho__time')
                if not date_tag:
                    continue

                # Преобразуем дату в объект datetime
                date_str = date_tag.text.strip().lower()
                if 'сегодня' in date_str:
                    pub_date = datetime.now()
                elif 'вчера' in date_str:
                    pub_date = datetime.now() - timedelta(days=1)
                else:
                    # Обработка формата "10 июля"
                    match = re.search(r'(\d{1,2})\s+([а-я]+)', date_str)
                    if match:
                        day = int(match.group(1))
                        month_str = match.group(2)[:3]
                        months = {
                            'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4,
                            'мая': 5, 'июн': 6, 'июл': 7, 'авг': 8,
                            'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
                        }
                        if month_str in months:
                            pub_date = datetime(datetime.now().year, months[month_str], day)
                        else:
                            pub_date = datetime.now()
                    else:
                        pub_date = datetime.now()

                # Пропускаем старые новости
                if pub_date < three_weeks_ago:
                    continue

                # Добавляем случайную задержку между запросами
                delay = random.uniform(2.0, 5.0)
                print(f"⏳ Задержка {delay:.1f} сек перед переходом на статью")
                time.sleep(delay)

                # Переходим на страницу статьи
                print(f"📄 Переходим на статью: {title}")
                driver.get(link)

                # Ожидаем загрузки контента
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.article_text_wrapper"))
                )

                # Имитация поведения на странице статьи
                human_like_interaction(driver)

                # Парсим полный текст статьи
                article_soup = BeautifulSoup(driver.page_source, 'html.parser')

                # Извлекаем основной текст
                content_div = article_soup.find('div', class_='article_text_wrapper')
                if not content_div:
                    print("⚠️ Не найден контент статьи")
                    driver.back()
                    time.sleep(1)
                    continue

                # Удаляем ненужные элементы
                for elem in content_div.select(
                        '.article_incut, .article_incut__link, .doc__announce, .article__subscribe, .doc__tags, .article__tools'):
                    elem.decompose()

                full_text = content_div.get_text(separator='\n', strip=True)

                # Проверяем ключевые слова в тексте
                KEYWORDS = ["энергетик", "виэ", "водород", "акб", "экологи", "декарбонизац",
                            "зелен", "возобнов", "электромобил", "экотех", "климат", "энергопереход",
                            "renewable", "solar", "wind", "battery", "hydrogen", "decarbonization"]

                content_lower = (title + " " + full_text).lower()
                if any(kw in content_lower for kw in KEYWORDS):
                    news_items.append({
                        "title": title,
                        "url": link,
                        "source": "Kommersant",
                        "date": pub_date.strftime("%Y-%m-%d"),
                        "preview": full_text[:200] + "..." if len(full_text) > 200 else full_text,
                        "full_text": full_text
                    })
                    print(f"✅ Найдена подходящая статья: {title}")
                else:
                    print(f"⏭️ Статья не соответствует тематике: {title}")

                # Возвращаемся к списку статей
                driver.back()
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article.rubric_lenta__item"))
                )
                time.sleep(random.uniform(1.0, 2.5))

            except Exception as e:
                print(f"⚠️ Ошибка при обработке статьи: {str(e)}")
                # Если возникла ошибка, перезагружаем основную страницу
                driver.get(base_url)
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article.rubric_lenta__item"))
                )
                continue

        return news_items

    except Exception as e:
        print(f"🚨 Критическая ошибка при парсинге Коммерсанта: {str(e)}")
        return []
    finally:
        # Всегда закрываем драйвер
        driver.quit()
        print("🔚 Драйвер браузера закрыт")


# Запуск парсера
print("=" * 50)
print("🟢 Начинаем парсинг Коммерсанта")
print("=" * 50)
start_time = time.time()
kommersant_news = parse_kommersant()
execution_time = time.time() - start_time

# Сохранение результатов
if kommersant_news:
    filename = f'kommersant_news_{datetime.now().strftime("%Y%m%d_%H%M")}.json'
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(kommersant_news, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Сохранено статей: {len(kommersant_news)} в файл {filename}")
else:
    print("⚠️ Не найдено подходящих статей")

print(f"⏱️ Время выполнения: {execution_time:.1f} секунд")
print("=" * 50)