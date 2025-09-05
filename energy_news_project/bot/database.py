# bot/database.py
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, Any
import logging

logger = logging.getLogger(__name__)


class SafeNewsDB:
    """Thread-safe news database with transactions, caching, and automatic backups."""

    def __init__(self, db_file="data/news_db.json", sent_ids_file="data/sent_ids.json", backup_interval=3600):
        self.db_file = db_file
        self.sent_ids_file = sent_ids_file
        self.backup_interval = backup_interval

        # Ensure directories exist
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.sent_ids_file), exist_ok=True)

        # Thread safety
        self._lock = threading.RLock()

        # In-memory data
        self.news_db: Dict[str, Any] = {}
        self.sent_ids: Set[str] = set()

        # Load existing data
        self._load_db()
        self._load_sent_ids()

        # Background backup
        self._last_backup = time.time()
        self._start_backup_thread()

        logger.info(f"Database initialized: {len(self.news_db)} news items, {len(self.sent_ids)} sent IDs")

    def _start_backup_thread(self):
        """Start background thread for periodic backups."""

        def backup_worker():
            while True:
                try:
                    time.sleep(300)  # Check every 5 minutes
                    if time.time() - self._last_backup > self.backup_interval:
                        self._create_backup()
                        self._last_backup = time.time()
                except Exception as e:
                    logger.error(f"Backup thread error: {e}")

        backup_thread = threading.Thread(target=backup_worker, daemon=True)
        backup_thread.start()

    def _create_backup(self):
        """Create backup files with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            with self._lock:
                # Backup news database
                backup_db_file = f"{self.db_file}.backup_{timestamp}"
                if os.path.exists(self.db_file):
                    shutil.copy2(self.db_file, backup_db_file)

                # Backup sent IDs
                backup_ids_file = f"{self.sent_ids_file}.backup_{timestamp}"
                if os.path.exists(self.sent_ids_file):
                    shutil.copy2(self.sent_ids_file, backup_ids_file)

                logger.info(f"Backup created: {backup_db_file}")

                # Clean old backups (keep only last 10)
                self._cleanup_old_backups()

        except Exception as e:
            logger.error(f"Backup creation failed: {e}")

    def _cleanup_old_backups(self):
        """Remove old backup files, keeping only the 10 most recent."""
        try:
            db_dir = os.path.dirname(self.db_file)
            db_name = os.path.basename(self.db_file)
            ids_name = os.path.basename(self.sent_ids_file)

            # Get all backup files
            db_backups = [f for f in os.listdir(db_dir) if f.startswith(f"{db_name}.backup_")]
            ids_backups = [f for f in os.listdir(db_dir) if f.startswith(f"{ids_name}.backup_")]

            # Sort by modification time and remove old ones
            for backups in [db_backups, ids_backups]:
                if len(backups) > 10:
                    backups.sort(key=lambda x: os.path.getmtime(os.path.join(db_dir, x)))
                    for old_backup in backups[:-10]:
                        os.remove(os.path.join(db_dir, old_backup))
                        logger.debug(f"Removed old backup: {old_backup}")

        except Exception as e:
            logger.error(f"Backup cleanup failed: {e}")

    def _load_db(self):
        """Load news database from file."""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.news_db = data
                    else:
                        logger.warning("Invalid database format, starting with empty database")
                        self.news_db = {}
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load database: {e}")
                # Try to load from latest backup
                self._restore_from_backup()

    def _load_sent_ids(self):
        """Load sent IDs from file."""
        if os.path.exists(self.sent_ids_file):
            try:
                with open(self.sent_ids_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.sent_ids = set(data)
                    else:
                        logger.warning("Invalid sent IDs format, starting with empty set")
                        self.sent_ids = set()
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load sent IDs: {e}")
                self.sent_ids = set()

    def _restore_from_backup(self):
        """Restore from the most recent backup."""
        try:
            db_dir = os.path.dirname(self.db_file)
            db_name = os.path.basename(self.db_file)

            backups = [f for f in os.listdir(db_dir) if f.startswith(f"{db_name}.backup_")]
            if not backups:
                logger.warning("No backups found")
                return

            # Get most recent backup
            latest_backup = max(backups, key=lambda x: os.path.getmtime(os.path.join(db_dir, x)))
            backup_path = os.path.join(db_dir, latest_backup)

            with open(backup_path, "r", encoding="utf-8") as f:
                self.news_db = json.load(f)

            logger.info(f"Restored from backup: {latest_backup}")

        except Exception as e:
            logger.error(f"Failed to restore from backup: {e}")
            self.news_db = {}

    def _save_db(self):
        """Save news database to file."""
        try:
            # Write to temporary file first
            temp_file = f"{self.db_file}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.news_db, f, ensure_ascii=False, indent=2)

            # Atomic move
            shutil.move(temp_file, self.db_file)

        except Exception as e:
            logger.error(f"Failed to save database: {e}")
            # Clean up temp file if it exists
            if os.path.exists(f"{self.db_file}.tmp"):
                os.remove(f"{self.db_file}.tmp")
            raise

    def _save_sent_ids(self):
        """Save sent IDs to file."""
        try:
            temp_file = f"{self.sent_ids_file}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(list(self.sent_ids), f, ensure_ascii=False, indent=2)

            shutil.move(temp_file, self.sent_ids_file)

        except Exception as e:
            logger.error(f"Failed to save sent IDs: {e}")
            if os.path.exists(f"{self.sent_ids_file}.tmp"):
                os.remove(f"{self.sent_ids_file}.tmp")
            raise

    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        with self._lock:
            old_news_db = self.news_db.copy()
            old_sent_ids = self.sent_ids.copy()

            try:
                yield
                self._save_db()
                self._save_sent_ids()
            except Exception as e:
                # Rollback on error
                self.news_db = old_news_db
                self.sent_ids = old_sent_ids
                logger.error(f"Transaction rolled back due to error: {e}")
                raise

    def add_news(self, news_id: str, news_data: dict, message_id: int, channel_id: str):
        """Add news item to database."""
        with self.transaction():
            self.news_db[news_id] = {
                "news_data": news_data,
                "message_id": message_id,
                "channel_id": channel_id,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            self.sent_ids.add(news_id)
            logger.debug(f"Added news: {news_id}")

    def get_news(self, news_id: str) -> Optional[dict]:
        """Get news item by ID."""
        with self._lock:
            return self.news_db.get(news_id)

    def update_news(self, news_id: str, updates: dict):
        """Update news item with support for nested keys like 'news_data.full_text'."""
        with self.transaction():
            if news_id not in self.news_db:
                logger.warning(f"News {news_id} not found for update")
                return False

            try:
                for key, value in updates.items():
                    if '.' in key:
                        # Handle nested keys like 'news_data.full_text'
                        parts = key.split('.')
                        current = self.news_db[news_id]

                        # Navigate to the parent of the target key
                        for part in parts[:-1]:
                            if part not in current:
                                current[part] = {}
                            current = current[part]

                        # Set the final value
                        final_key = parts[-1]
                        current[final_key] = value
                        logger.debug(f"Updated {key} = {value}")
                    else:
                        # Direct key update
                        self.news_db[news_id][key] = value
                        logger.debug(f"Updated {key} = {value}")

                # Always update the timestamp
                self.news_db[news_id]["updated_at"] = datetime.now().isoformat()

                logger.debug(f"Successfully updated news {news_id}")
                return True

            except Exception as e:
                logger.error(f"Error updating news {news_id}: {e}")
                raise  # This will trigger transaction rollback

    def delete_news(self, news_id: str):
        """Delete news item."""
        with self.transaction():
            if news_id in self.news_db:
                del self.news_db[news_id]
                self.sent_ids.discard(news_id)
                logger.debug(f"Deleted news: {news_id}")
                return True
            return False

    def is_sent(self, news_id: str) -> bool:
        """Check if news was already sent."""
        with self._lock:
            return news_id in self.sent_ids

    def get_all_news_ids(self) -> Set[str]:
        """Get all news IDs."""
        with self._lock:
            return set(self.news_db.keys())

    def get_stats(self) -> dict:
        """Get database statistics."""
        with self._lock:
            total_news = len(self.news_db)
            sent_count = len(self.sent_ids)

            # Count by status
            pending = 0
            published = 0
            rejected = 0

            for news_data in self.news_db.values():
                status = news_data.get("status", "pending")
                if status == "pending":
                    pending += 1
                elif status == "published":
                    published += 1
                elif status == "rejected":
                    rejected += 1

            return {
                "total_news": total_news,
                "sent_count": sent_count,
                "pending": pending,
                "published": published,
                "rejected": rejected,
                "db_size_mb": os.path.getsize(self.db_file) / 1024 / 1024 if os.path.exists(self.db_file) else 0
            }

    def cleanup_old_news(self, days: int = 30):
        """Remove news older than specified days."""
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff_date.isoformat()

        with self.transaction():
            to_remove = []
            for news_id, news_data in self.news_db.items():
                created_at = news_data.get("created_at", "")
                if created_at and created_at < cutoff_str:
                    to_remove.append(news_id)

            removed_count = 0
            for news_id in to_remove:
                if self.delete_news(news_id):
                    removed_count += 1

            logger.info(f"Cleaned up {removed_count} old news items")
            return removed_count

    def clear_all(self):
        """Clear all data (use with caution)."""
        with self.transaction():
            self.news_db.clear()
            self.sent_ids.clear()
            logger.warning("Database cleared")

    def force_save(self):
        """Force save all data to disk."""
        with self._lock:
            self._save_db()
            self._save_sent_ids()
            logger.info("Database force saved")

    def __len__(self):
        """Return number of news items."""
        with self._lock:
            return len(self.news_db)

    def __contains__(self, news_id):
        """Check if news ID exists."""
        with self._lock:
            return news_id in self.news_db

    # Compatibility methods for legacy code
    def save_db(self):
        """Legacy compatibility method - maps to force_save()."""
        self.force_save()

    def save_sent_ids(self):
        """Legacy compatibility method - maps to force_save()."""
        self.force_save()