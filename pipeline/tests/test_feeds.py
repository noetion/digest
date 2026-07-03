from __future__ import annotations

from datetime import UTC, datetime, timedelta

from digest.config import Feed
from digest.feeds import _parse_feed

FEED = Feed(name="Test", url="https://example.com/feed", topic="ai")


def _rss(items: str) -> bytes:
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test</title>{items}</channel></rss>""".encode()


def _item(title: str, link: str, pubdate: str = "") -> str:
    date_tag = f"<pubDate>{pubdate}</pubDate>" if pubdate else ""
    return f"<item><title>{title}</title><link>{link}</link>{date_tag}</item>"


def test_fresh_entries_kept_and_stale_dropped() -> None:
    now = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    fresh = (now - timedelta(hours=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    stale = (now - timedelta(hours=60)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    raw = _rss(
        _item("Fresh story", "https://example.com/fresh", fresh)
        + _item("Stale story", "https://example.com/stale", stale)
    )
    entries = _parse_feed(FEED, raw, now)
    assert [e.title for e in entries] == ["Fresh story"]


def test_undated_entries_pass_through_for_dedup_to_handle() -> None:
    now = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    raw = _rss(_item("No date", "https://example.com/nodate"))
    entries = _parse_feed(FEED, raw, now)
    assert len(entries) == 1
    assert entries[0].published is None


def test_entries_missing_title_or_link_skipped() -> None:
    now = datetime.now(tz=UTC)
    raw = _rss("<item><title>Only title</title></item>")
    assert _parse_feed(FEED, raw, now) == []


def test_source_and_topic_attached() -> None:
    now = datetime.now(tz=UTC)
    raw = _rss(_item("A", "https://example.com/a"))
    entry = _parse_feed(FEED, raw, now)[0]
    assert entry.source == "Test"
    assert entry.topic == "ai"
