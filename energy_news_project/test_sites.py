import requests
from bs4 import BeautifulSoup

TEST_SITES = {
    "E-Energy": "https://eenergy.media/rubric/news",
    "In-Power": "https://www.in-power.ru/news/alternativnayaenergetika",
    "Neftegaz": "https://neftegaz.ru/news/Alternative-energy/",
    "Oilcapital": "https://oilcapital.ru/tags/vie",
    "RENEN": "https://renen.ru/"
}

headers = {"User-Agent": "Mozilla/5.0"}

def test_site(name, url):
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # универсальный вариант — берём первые ссылки с текстом
        articles = soup.find_all("a", href=True)
        print(f"\n=== {name} ({url}) ===")
        count = 0
        for a in articles:
            text = a.get_text(strip=True)
            href = a["href"]
            if text and len(text) > 30:  # фильтр по длине
                print(f"- {text[:100]} -> {href}")
                count += 1
            if count >= 5:
                break
        if count == 0:
            print("⚠️ Новости не найдены (нужны точные селекторы).")
    except Exception as e:
        print(f"❌ Ошибка для {name}: {e}")

if __name__ == "__main__":
    for site, url in TEST_SITES.items():
        test_site(site, url)
