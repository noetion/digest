"""One-off feed probe: HTTP status + 48h fresh count. Run from pipeline/."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from digest.config import USER_AGENT, Feed
from digest.feeds import FRESH_WINDOW, _entry_published, _parse_feed

CANDIDATES = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "ai"),
    ("TechCrunch", "https://techcrunch.com/feed/", "startups"),
    ("The Verge", "https://www.theverge.com/rss/index.xml", "big-tech"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "ai"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "big-tech"),
    ("Ars Technica AI", "https://arstechnica.com/ai/feed/", "ai"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "ai"),
    ("VentureBeat main", "https://venturebeat.com/feed/", "ai"),
    ("Hacker News 150+", "https://hnrss.org/frontpage?points=150", "dev-tools"),
    ("The Decoder", "https://the-decoder.com/feed/", "ai"),
    ("The Register AI", "https://www.theregister.com/software/ai_ml/headlines.atom", "ai"),
    ("MIT Tech Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "ai"),
    ("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss", "ai"),
    ("IEEE Spectrum AI", "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", "ai"),
    ("AI News", "https://www.artificialintelligence-news.com/feed/", "ai"),
    ("MarkTechPost", "https://www.marktechpost.com/feed/", "ai"),
    ("SiliconANGLE AI", "https://siliconangle.com/category/ai/feed/", "ai"),
    ("Import AI (Substack)", "https://importai.substack.com/feed", "ai"),
    ("Ben's Bites", "https://www.bensbites.com/feed", "ai"),
    ("TLDR AI", "https://tldr.tech/ai/rss", "ai"),
    ("OpenAI Blog", "https://openai.com/blog/rss.xml", "ai"),
    ("Google AI Blog", "https://blog.google/technology/ai/rss/", "ai"),
    ("Anthropic News", "https://www.anthropic.com/news/rss", "ai"),
    ("SemiAnalysis", "https://www.semianalysis.com/feed", "chips"),
    ("Tom's Hardware AI", "https://www.tomshardware.com/feeds/tag/artificial-intelligence", "chips"),
]

now = datetime.now(tz=UTC)
print(f"{'Feed':<22} {'HTTP':>4} {'48h':>4} {'Newest age (h)':>14}")
print("-" * 50)
for name, url, topic in CANDIDATES:
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20)
        status = r.status_code
        if status != 200:
            print(f"{name:<22} {status:>4}    -              -")
            continue
        feed = Feed(name=name, url=url, topic=topic)
        fresh = _parse_feed(feed, r.content, now)
        newest_h = "-"
        import feedparser

        parsed = feedparser.parse(r.content)
        if parsed.entries:
            pub = _entry_published(parsed.entries[0])
            if pub:
                newest_h = f"{(now - pub).total_seconds() / 3600:.0f}"
        print(f"{name:<22} {status:>4} {len(fresh):>4} {newest_h:>14}")
    except Exception as exc:
        print(f"{name:<22} FAIL    -   {exc}")
