"""Evaluate configured feeds: HTTP, 48h volume, freshness. Run from pipeline/."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import feedparser
import httpx

from digest.config import FEEDS, USER_AGENT
from digest.feeds import FRESH_WINDOW, _entry_published, _parse_feed

now = datetime.now(tz=UTC)
print(f"Evaluated {now.strftime('%Y-%m-%d %H:%M UTC')} | window = {FRESH_WINDOW}\n")
print(f"{'Feed':<28} {'48h':>4} {'Feed':>5} {'Newest':>8} {'Status':<8}  Topic")
print("-" * 72)

for feed in FEEDS:
    try:
        r = httpx.get(feed.url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=25)
        if r.status_code != 200:
            print(f"{feed.name:<28}    -     -        -  HTTP {r.status_code}  {feed.topic}")
            continue
        parsed = feedparser.parse(r.content)
        fresh = _parse_feed(feed, r.content, now)
        newest = "-"
        if parsed.entries:
            pub = _entry_published(parsed.entries[0])
            if pub:
                newest = f"{(now - pub).total_seconds() / 3600:.0f}h"
        n = len(fresh)
        if n == 0:
            status = "DEAD"
        elif n < 2:
            status = "THIN"
        elif n >= 5:
            status = "STRONG"
        else:
            status = "OK"
        print(f"{feed.name:<28} {n:>4} {len(parsed.entries):>5} {newest:>8} {status:<8}  {feed.topic}")
    except Exception as exc:
        print(f"{feed.name:<28}    -     -        -  FAIL     {exc}")
