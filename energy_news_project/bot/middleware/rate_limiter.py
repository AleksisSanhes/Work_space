# bot/middleware/rate_limiter.py
import time
import logging
from collections import defaultdict, deque
from typing import Dict, Optional
from telegram.ext import BaseRateLimiter
from telegram import Update

logger = logging.getLogger(__name__)


class RateLimiter(BaseRateLimiter):
    """Custom rate limiter with per-user and global limits."""

    def __init__(self,
                 global_rate: int = 30,  # requests per minute globally
                 user_rate: int = 10,  # requests per minute per user
                 window_size: int = 60):  # time window in seconds

        self.global_rate = global_rate
        self.user_rate = user_rate
        self.window_size = window_size

        # Storage for request timestamps
        self.global_requests: deque = deque()
        self.user_requests: Dict[int, deque] = defaultdict(lambda: deque())

        # Admin users (can be configured)
        self.admin_users = set()

    def add_admin_user(self, user_id: int):
        """Add admin user (no rate limiting)."""
        self.admin_users.add(user_id)
        logger.info(f"Added admin user: {user_id}")

    def _clean_old_requests(self, request_queue: deque, current_time: float):
        """Remove requests older than window_size."""
        while request_queue and current_time - request_queue[0] > self.window_size:
            request_queue.popleft()

    async def process_request(self,
                              callback,
                              update: Update,
                              application,
                              check_result=None) -> None:
        """Process request with rate limiting."""
        current_time = time.time()

        # Get user ID
        user_id = None
        if update.effective_user:
            user_id = update.effective_user.id

        # Skip rate limiting for admin users
        if user_id in self.admin_users:
            await callback()
            return

        # Clean old requests
        self._clean_old_requests(self.global_requests, current_time)
        if user_id:
            self._clean_old_requests(self.user_requests[user_id], current_time)

        # Check global rate limit
        if len(self.global_requests) >= self.global_rate:
            logger.warning(f"Global rate limit exceeded")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⏱️ Система перегружена. Попробуйте позже."
                )
            return

        # Check user rate limit
        if user_id and len(self.user_requests[user_id]) >= self.user_rate:
            logger.warning(f"User rate limit exceeded for user {user_id}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⏱️ Слишком много запросов. Подождите минуту."
                )
            return

        # Record request
        self.global_requests.append(current_time)
        if user_id:
            self.user_requests[user_id].append(current_time)

        # Execute callback
        try:
            await callback()
        except Exception as e:
            logger.error(f"Callback execution error: {e}")
            raise

    def get_stats(self) -> Dict:
        """Get rate limiter statistics."""
        current_time = time.time()

        # Clean old requests first
        self._clean_old_requests(self.global_requests, current_time)

        active_users = 0
        for user_queue in self.user_requests.values():
            self._clean_old_requests(user_queue, current_time)
            if len(user_queue) > 0:
                active_users += 1

        return {
            "global_requests_current_window": len(self.global_requests),
            "global_rate_limit": self.global_rate,
            "user_rate_limit": self.user_rate,
            "active_users": active_users,
            "admin_users": len(self.admin_users),
            "window_size": self.window_size
        }