import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
from deep_translator import GoogleTranslator
import logging

logger = logging.getLogger(__name__)

EXPANDED_KEYWORDS = [
    "энергетик", "виэ", "водород", "акб", "экологи", "декарбонизац", "возобнов", "электромобил",
    "экотех", "климат", "энергопереход", "renewable", "solar", "wind", "battery", "hydrogen",
    "decarbonization", "sustainability", "green energy", "clean tech", "photovoltaic", "wind turbine",
    "энергоэффективность", "биотопливо", "геотермальный", "приливная энергия", "энергосбережение"
]

def load_classification_model():
    logger.info("Загрузка модели классификации...")
    try:
        model_name = "cointegrated/rubert-tiny2-cedr-emotion-detection"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        classifier = pipeline(
            "text-classification",
            model=model,
            tokenizer=tokenizer,
            device=0 if torch.cuda.is_available() else -1
        )
        logger.info("Модель загружена")
        return classifier
    except Exception as e:
        logger.error(f"Ошибка загрузки модели: {str(e)}")
        return None

def is_energy_related(text, classifier=None, threshold=0.90):
    if not text.strip():
        return False, "Пустой текст"
    text_lower = text.lower()
    keyword_count = sum(1 for keyword in EXPANDED_KEYWORDS if keyword.lower() in text_lower)
    if keyword_count >= 2:
        return True, f"Найдено {keyword_count} ключевых слов"
    if not classifier:
        return keyword_count > 0, "Проверка только по ключевым словам"
    try:
        result = classifier(text[:400], truncation=True, max_length=512)
        for res in result:
            if res['label'] == 'neutral' and res['score'] > threshold:
                return True, f"ИИ-классификация ({res['score']:.2f})"
        return False, "Нерелевантно"
    except Exception as e:
        logger.error(f"Ошибка классификации: {str(e)}")
        return keyword_count > 0, "Ошибка ИИ"

def translate_text(text, src="en", dest="ru", source_name=None, article_url=None):
    if not text.strip():
        return text
    try:
        max_chunk_size = 4500
        chunks = [text[i:i + max_chunk_size] for i in range(0, len(text), max_chunk_size)]
        translated = [GoogleTranslator(source=src, target=dest).translate(chunk) for chunk in chunks]
        return " ".join(translated)
    except Exception as e:
        logger.warning(f"Ошибка перевода ({source_name or '???'} - {article_url or ''}): {str(e)}")
        return text
