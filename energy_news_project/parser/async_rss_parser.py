# parser/async_rss_parser.py
import asyncio
import aiohttp
import feedparser
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
import time
from urllib.parse import urljoin, urlparse
import hashlib

from parser.utils import clean_text
from parser.nlp_filter import is_energy_related, translate_text
from parser.stats import update_stats

logger = logging.getLogger(__name__)


@dataclass
class FeedConfig:
    url: str
    name: str
    language: str = "ru"
    custom_headers: Dict[str, str] = field(default_factory=dict)
    rate_limit_delay: float = 1.0
    max_articles: int = 100
    enabled: bool = True


@dataclass
class ParsingResult:
    news_items: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)
    processing_time: float = 0.0


class AsyncRSSParser:
    """High-performance async RSS parser with connection pooling and rate limiting."""

    def __init__(self, max_workers: int = 10, timeout: int = 30, max_connections: int = 100):
        self.max_workers = max_workers
        self.timeout = timeout
        self.max_connections = max_connections
        self.session: Optional[aiohttp.ClientSession] = None
        self._rate_limiters: Dict[str, float] = {}

        # Feed configurations
        self.feeds = [
            FeedConfig("https://lenta.ru/rss/news", "Lenta.ru"),
            FeedConfig("https://www.interfax.ru/rss.asp", "Interfax"),
            FeedConfig("https://ria.ru/export/rss2/archive/index.xml", "RIA Novosti"),
            FeedConfig("https://www.vedomosti.ru/rss/news", "Vedomosti"),
            FeedConfig("https://hightech.fm/feed", "Hi-Tech Mail.ru"),
            FeedConfig("https://renen.ru/feed/", "RENEN - ВИЭ"),
            FeedConfig("https://energovector.com/feed/", "Энерговектор"),
            FeedConfig("https://cleantechnica.com/feed/", "CleanTechnica", "en"),
            FeedConfig("https://www.h2-view.com/feed/", "H2 View", "en"),
            FeedConfig("https://energynews.us/feed/", "Energy News Network", "en"),
            FeedConfig("https://www.greentechmedia.com/feed", "Greentech Media", "en"),
            FeedConfig("https://www.hydrogenfuelnews.com/feed/", "Hydrogen Fuel News", "en"),
            FeedConfig("https://www.pv-magazine.com/feed/", "PV Magazine", "en"),
            FeedConfig("https://www.renewableenergyworld.com/feed/", "Renewable Energy World", "en"),
            FeedConfig("https://www.energy-storage.news/feed/", "Energy Storage News", "en"),
            FeedConfig("https://eenergy.media/rubric/news/feed", "E-Energy"),
            FeedConfig("https://oilcapital.ru/rss", "Oilcapital"),
        ]

    async def __aenter__(self):
        """Async context manager entry."""
        await self._create_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._close_session()

    async def _create_session(self):
        """Create aiohttp session with optimized settings."""
        connector = aiohttp.TCPConnector(
            limit=self.max_connections,
            limit_per_host=20,
            ttl_dns_cache=300,
            use_dns_cache=True,
            keepalive_timeout=60,
            enable_cleanup_closed=True
        )

        timeout = aiohttp.ClientTimeout(total=self.timeout, connect=10)

        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; NewsBot/1.0)',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }

        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers,
            raise_for_status=False
        )

        logger.info("HTTP session created with connection pooling")

    async def _close_session(self):
        """Close aiohttp session."""
        if self.session:
            await self.session.close()
            # Wait for underlying connections to close
            await asyncio.sleep(0.25)
            logger.info("HTTP session closed")

    async def _rate_limit(self, domain: str, delay: float):
        """Apply rate limiting per domain."""
        current_time = time.time()
        last_request = self._rate_limiters.get(domain, 0)

        if current_time - last_request < delay:
            sleep_time = delay - (current_time - last_request)
            await asyncio.sleep(sleep_time)

        self._rate_limiters[domain] = time.time()

    async def _fetch_content(self, url: str, headers: Optional[Dict] = None) -> Optional[bytes]:
        """Fetch content from URL with retries and error handling."""
        if not self.session:
            raise RuntimeError("Session not initialized")

        domain = urlparse(url).netloc
        await self._rate_limit(domain, 1.0)

        request_headers = headers or {}

        for attempt in range(3):
            try:
                async with self.session.get(url, headers=request_headers) as response:
                    if response.status == 200:
                        content = await response.read()
                        return content
                    elif response.status == 429:
                        # Rate limited
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"Rate limited for {url}, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                    else:
                        logger.warning(f"HTTP {response.status} for {url}")

            except asyncio.TimeoutError:
                logger.warning(f"Timeout for {url} (attempt {attempt + 1})")
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                await asyncio.sleep(2 ** attempt)

        return None

    async def _extract_full_text(self, url: str) -> str:
        """Extract full text from article URL."""
        try:
            content = await self._fetch_content(url)
            if not content:
                return ""

            # Parse with BeautifulSoup in thread pool to avoid blocking
            from bs4 import BeautifulSoup

            def parse_html(content_bytes):
                try:
                    soup = BeautifulSoup(content_bytes, "html.parser")

                    # Remove unwanted elements
                    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                        tag.decompose()

                    # Try different content selectors
                    content_selectors = [
                        'article', '.content', '.post-content', '.entry-content',
                        '.article-body', '.post-body', '#content', '.main-content'
                    ]

                    text = ""
                    for selector in content_selectors:
                        elements = soup.select(selector)
                        if elements:
                            text = ' '.join([el.get_text(strip=True) for el in elements])
                            break

                    # Fallback to all paragraphs
                    if not text or len(text) < 100:
                        paragraphs = soup.find_all('p')
                        text = ' '.join(
                            [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30])

                    return clean_text(text)

                except Exception as e:
                    logger.error(f"HTML parsing error for {url}: {e}")
                    return ""

            loop = asyncio.get_event_loop()
            full_text = await loop.run_in_executor(None, parse_html, content)
            return full_text

        except Exception as e:
            logger.error(f"Full text extraction error for {url}: {e}")
            return ""

    async def _parse_single_feed(self, feed_config: FeedConfig, classifier, stats) -> List[Dict]:
        """Parse a single RSS feed."""
        if not feed_config.enabled:
            return []

        results = []
        cutoff_date = datetime.now() - timedelta(days=21)

        try:
            # Fetch RSS content
            content = await self._fetch_content(
                feed_config.url,
                feed_config.custom_headers
            )

            if not content:
                update_stats(stats, feed_config.name, "fetch_failed")
                return results

            # Parse RSS in thread pool
            def parse_rss(content_bytes):
                return feedparser.parse(content_bytes)

            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, parse_rss, content)

            if not hasattr(feed, 'entries') or not feed.entries:
                update_stats(stats, feed_config.name, "no_entries")
                return results

            # Limit articles per feed
            entries = feed.entries[:feed_config.max_articles]

            # Process entries concurrently with semaphore
            semaphore = asyncio.Semaphore(5)  # Limit concurrent article processing

            async def process_entry(entry):
                async with semaphore:
                    return await self._process_entry(
                        entry, feed_config, classifier, cutoff_date
                    )

            # Process all entries
            entry_results = await asyncio.gather(
                *[process_entry(entry) for entry in entries],
                return_exceptions=True
            )

            # Collect successful results
            for result in entry_results:
                if isinstance(result, dict):
                    results.append(result)
                    update_stats(stats, feed_config.name, "accepted")
                elif isinstance(result, Exception):
                    logger.error(f"Entry processing error in {feed_config.name}: {result}")
                    update_stats(stats, feed_config.name, "processing_error")
                else:
                    update_stats(stats, feed_config.name, "not_relevant")

            logger.info(f"Processed {len(results)} articles from {feed_config.name}")

        except Exception as e:
            logger.error(f"Feed processing error for {feed_config.name}: {e}")
            update_stats(stats, feed_config.name, "feed_error")

        return results

    async def _process_entry(self, entry, feed_config: FeedConfig, classifier, cutoff_date) -> Optional[Dict]:
        """Process a single feed entry."""
        try:
            # Check publication date
            pub_date = datetime.now()
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    pub_date = datetime(*entry.published_parsed[:6])
                except (ValueError, TypeError):
                    pass

            if pub_date < cutoff_date:
                return None

            # Extract basic info
            title = getattr(entry, 'title', '')
            summary = getattr(entry, 'summary', '')
            link = getattr(entry, 'link', '')

            if not title or not link:
                return None

            # Get full text
            full_text = await self._extract_full_text(link)

            # Combine text for relevance check
            combined_text = f"{title} {summary} {full_text}".strip()

            # Translate if needed
            if feed_config.language == "en" and combined_text:
                try:
                    combined_text = await asyncio.get_event_loop().run_in_executor(
                        None, translate_text, combined_text, "en", "ru", feed_config.name, link
                    )
                    title = await asyncio.get_event_loop().run_in_executor(
                        None, translate_text, title, "en", "ru", feed_config.name, link
                    )
                    if summary:
                        summary = await asyncio.get_event_loop().run_in_executor(
                            None, translate_text, summary, "en", "ru", feed_config.name, link
                        )
                except Exception as e:
                    logger.warning(f"Translation error for {link}: {e}")

            # Check relevance
            relevant, reason = is_energy_related(combined_text, classifier)
            if not relevant:
                return None

            # Create news item
            news_item = {
                "title": clean_text(title),
                "url": link,
                "date": pub_date.strftime("%Y-%m-%d %H:%M"),
                "source": feed_config.name,
                "preview": clean_text(summary or combined_text)[:300] + "...",
                "full_text": clean_text(full_text),
                "relevance_reason": reason,
                "language": feed_config.language,
                "processed_at": datetime.now().isoformat()
            }

            return news_item

        except Exception as e:
            logger.error(f"Entry processing error: {e}")
            return None

    async def parse_all_feeds(self, classifier=None, stats=None,
                              enabled_feeds: Optional[Set[str]] = None) -> ParsingResult:
        """Parse all RSS feeds concurrently."""
        start_time = time.time()

        # Filter feeds if specified
        feeds_to_process = self.feeds
        if enabled_feeds:
            feeds_to_process = [f for f in self.feeds if f.name in enabled_feeds]

        logger.info(f"Starting to parse {len(feeds_to_process)} RSS feeds")

        # Create semaphore to limit concurrent feeds
        semaphore = asyncio.Semaphore(self.max_workers)

        async def parse_with_semaphore(feed_config):
            async with semaphore:
                return await self._parse_single_feed(feed_config, classifier, stats)

        # Process all feeds concurrently
        try:
            feed_results = await asyncio.gather(
                *[parse_with_semaphore(feed) for feed in feeds_to_process],
                return_exceptions=True
            )

            all_news = []
            errors = []

            for i, result in enumerate(feed_results):
                if isinstance(result, list):
                    all_news.extend(result)
                elif isinstance(result, Exception):
                    feed_name = feeds_to_process[i].name
                    error_msg = f"Feed {feed_name} failed: {result}"
                    errors.append(error_msg)
                    logger.error(error_msg)

            # Remove duplicates based on URL
            seen_urls = set()
            unique_news = []

            for item in all_news:
                url = item.get('url', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_news.append(item)

            processing_time = time.time() - start_time

            logger.info(
                f"Parsing completed: {len(unique_news)} unique articles "
                f"from {len(all_news)} total in {processing_time:.2f}s"
            )

            return ParsingResult(
                news_items=unique_news,
                errors=errors,
                stats=stats or {},
                processing_time=processing_time
            )

        except Exception as e:
            logger.error(f"Critical parsing error: {e}")
            return ParsingResult(
                news_items=[],
                errors=[f"Critical error: {e}"],
                processing_time=time.time() - start_time
            )

    def add_feed(self, url: str, name: str, **kwargs):
        """Add a new feed configuration."""
        feed_config = FeedConfig(url=url, name=name, **kwargs)
        self.feeds.append(feed_config)
        logger.info(f"Added feed: {name} ({url})")

    def remove_feed(self, name: str) -> bool:
        """Remove a feed by name."""
        original_count = len(self.feeds)
        self.feeds = [f for f in self.feeds if f.name != name]
        removed = len(self.feeds) < original_count
        if removed:
            logger.info(f"Removed feed: {name}")
        return removed

    def get_feed_status(self) -> List[Dict]:
        """Get status of all configured feeds."""
        return [
            {
                "name": feed.name,
                "url": feed.url,
                "language": feed.language,
                "enabled": feed.enabled,
                "rate_limit": feed.rate_limit_delay,
                "max_articles": feed.max_articles
            }
            for feed in self.feeds
        ]

    def enable_feed(self, name: str) -> bool:
        """Enable a feed by name."""
        for feed in self.feeds:
            if feed.name == name:
                feed.enabled = True
                logger.info(f"Enabled feed: {name}")
                return True
        return False

    def disable_feed(self, name: str) -> bool:
        """Disable a feed by name."""
        for feed in self.feeds:
            if feed.name == name:
                feed.enabled = False
                logger.info(f"Disabled feed: {name}")
                return True
        return False


# Convenience function for backward compatibility
async def parse_all_feeds(classifier=None, stats=None) -> List[Dict]:
    """Parse all feeds using the async parser."""
    async with AsyncRSSParser() as parser:
        result = await parser.parse_all_feeds(classifier, stats)
        return result.news_items