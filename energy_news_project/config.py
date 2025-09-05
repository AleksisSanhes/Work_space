# config.py
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class TelegramConfig:
    """Конфигурация для Telegram API."""

    # Основные настройки
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "8217915867:AAFLPnQmnxhHmjloF4Ct3HhR9jjRjVYV6C8")
    moderation_channel: str = os.getenv("MODERATION_CHANNEL", "-1002996332660")
    publish_channel: str = os.getenv("PUBLISH_CHANNEL", "-1003006895565")

    # Настройки retry и задержек
    retry_attempts: int = int(os.getenv("TELEGRAM_RETRY_ATTEMPTS", "5"))
    flood_control_delay: float = float(os.getenv("TELEGRAM_FLOOD_DELAY", "1.5"))
    max_message_length: int = int(os.getenv("TELEGRAM_MAX_MESSAGE_LENGTH", "4000"))

    # Circuit breaker настройки
    circuit_breaker_failure_threshold: int = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
    circuit_breaker_recovery_timeout: float = float(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60.0"))


@dataclass
class DatabaseConfig:
    """Конфигурация для базы данных."""

    db_file: str = os.getenv("DB_FILE", "data/news_db.json")
    sent_ids_file: str = os.getenv("SENT_IDS_FILE", "data/sent_ids.json")
    backup_interval: int = int(os.getenv("DB_BACKUP_INTERVAL", "3600"))  # 1 hour
    auto_cleanup_days: int = int(os.getenv("DB_CLEANUP_DAYS", "30"))


@dataclass
class AppConfig:
    """Основная конфигурация приложения."""

    telegram: TelegramConfig
    database: DatabaseConfig

    # Общие настройки
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    data_dir: str = os.getenv("DATA_DIR", "data")
    logs_dir: str = os.getenv("LOGS_DIR", "logs")

    @classmethod
    def load(cls) -> "AppConfig":
        """Загрузить конфигурацию из переменных окружения."""
        return cls(
            telegram=TelegramConfig(),
            database=DatabaseConfig()
        )


# Глобальный экземпляр конфигурации
config = AppConfig.load()