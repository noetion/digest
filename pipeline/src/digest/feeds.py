"""Stage 2a: fetch RSS feeds and collect fresh candidate entries."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from time import mktime

import feedparser
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import FEEDS, USER_AGENT, Feed
from .models import FeedEntry

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)
# 48h rather than 24h: dedup state already prevents repeats, and the wider
# window means a failed run's stories still make the next day's digest
# instead of being lost forever.
FRESH_WINDOW = timedelta(hours=48)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=15), reraise=True)
def _download(url: str) -> bytes:
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.content


def _entry_published(entry: feedparser.FeedParserDict) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = entry.get(attr)
        if parsed:
            return datetime.fromtimestamp(mktime(parsed), tz=UTC)
    return None


def _parse_feed(feed: Feed, raw: bytes, now: datetime) -> list[FeedEntry]:
    parsed = feedparser.parse(raw)
    entries: list[FeedEntry] = []
    for entry in parsed.entries:
        url = entry.get("link", "")
        title = entry.get("title", "").strip()
        if not url or not title:
            continue
        published = _entry_published(entry)
        # Entries without a date fall through here and rely on dedup state instead.
        if published is not None and now - published > FRESH_WINDOW:
            continue
        entries.append(
            FeedEntry(
                title=title,
                url=url,
                source=feed.name,
                topic=feed.topic,
                published=published,
                summary=entry.get("summary", ""),
            )
        )
    return entries


def fetch_all_feeds(now: datetime | None = None) -> list[FeedEntry]:
    """Fetch every configured feed with per-feed failure isolation."""
    now = now or datetime.now(tz=UTC)
    candidates: list[FeedEntry] = []
    for feed in FEEDS:
        try:
            raw = _download(feed.url)
            entries = _parse_feed(feed, raw, now)
            logger.info("Feed %s: %d fresh entries", feed.name, len(entries))
            candidates.extend(entries)
        except Exception:
            logger.warning("Feed %s failed, skipping", feed.name, exc_info=True)
    return candidates
