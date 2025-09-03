# config.py
import os
from dataclasses import dataclass
from typing import List, Dict
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed

@dataclass
class TelegramConfig:
    bot_token: str
    moderation_channel: str
    publish_channel: str
    max_message_length: int = 4000
    retry_attempts: int = 5
    flood_control_delay: float = 1.5


@dataclass
class ParserConfig:
    max_workers: int = 10
    request_timeout: int = 30
    retry_attempts: int = 5
    days_back: int = 21
    batch_size: int = 50


@dataclass
class DatabaseConfig:
    db_file: str = "data/news_db.json"
    sent_ids_file: str = "data/sent_ids.json"
    backup_interval: int = 3600  # seconds


@dataclass
class Config:
    telegram: TelegramConfig
    parser: ParserConfig
    database: DatabaseConfig
    debug: bool = False
    log_level: str = "INFO"


def load_config() -> Config:
    """Load configuration from environment variables and config file."""

    # Try to load from config file first
    config_file = os.getenv("CONFIG_FILE", "config.json")
    config_data = {}

    if os.path.exists(config_file):
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)

    # Override with environment variables
    telegram_config = TelegramConfig(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", config_data.get("telegram", {}).get("bot_token", "")),
        moderation_channel=os.getenv("MODERATION_CHANNEL",
                                     config_data.get("telegram", {}).get("moderation_channel", "-1002996332660")),
        publish_channel=os.getenv("PUBLISH_CHANNEL",
                                  config_data.get("telegram", {}).get("publish_channel", "-1003006895565")),
        max_message_length=int(
            os.getenv("MAX_MESSAGE_LENGTH", config_data.get("telegram", {}).get("max_message_length", 4000))),
        retry_attempts=int(
            os.getenv("TELEGRAM_RETRY_ATTEMPTS", config_data.get("telegram", {}).get("retry_attempts", 5))),
        flood_control_delay=float(
            os.getenv("FLOOD_CONTROL_DELAY", config_data.get("telegram", {}).get("flood_control_delay", 1.5)))
    )

    parser_config = ParserConfig(
        max_workers=int(os.getenv("PARSER_MAX_WORKERS", config_data.get("parser", {}).get("max_workers", 10))),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", config_data.get("parser", {}).get("request_timeout", 30))),
        retry_attempts=int(os.getenv("PARSER_RETRY_ATTEMPTS", config_data.get("parser", {}).get("retry_attempts", 5))),
        days_back=int(os.getenv("DAYS_BACK", config_data.get("parser", {}).get("days_back", 21))),
        batch_size=int(os.getenv("BATCH_SIZE", config_data.get("parser", {}).get("batch_size", 50)))
    )

    database_config = DatabaseConfig(
        db_file=os.getenv("DB_FILE", config_data.get("database", {}).get("db_file", "data/news_db.json")),
        sent_ids_file=os.getenv("SENT_IDS_FILE",
                                config_data.get("database", {}).get("sent_ids_file", "data/sent_ids.json")),
        backup_interval=int(os.getenv("BACKUP_INTERVAL", config_data.get("database", {}).get("backup_interval", 3600)))
    )

    return Config(
        telegram=telegram_config,
        parser=parser_config,
        database=database_config,
        debug=os.getenv("DEBUG", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", config_data.get("log_level", "INFO"))
    )


def create_sample_config():
    """Create a sample configuration file."""
    sample_config = {
        "telegram": {
            "bot_token": "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8",
            "moderation_channel": "-1002996332660",
            "publish_channel": "-1003006895565",
            "max_message_length": 4000,
            "retry_attempts": 5,
            "flood_control_delay": 1.5
        },
        "parser": {
            "max_workers": 10,
            "request_timeout": 30,
            "retry_attempts": 5,
            "days_back": 21,
            "batch_size": 50
        },
        "database": {
            "db_file": "data/news_db.json",
            "sent_ids_file": "data/sent_ids.json",
            "backup_interval": 3600
        },
        "debug": False,
        "log_level": "INFO"
    }

    with open("config.json.example", "w", encoding="utf-8") as f:
        json.dump(sample_config, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    create_sample_config()
    print("Sample configuration file created: config.json.example")