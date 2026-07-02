"""Seen-URL state: never process the same article twice.

State lives in data/seen.json (committed by the pipeline) as
{url_hash: iso_date} and is pruned after 14 days.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .models import FeedEntry

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=14)


def canonicalize_url(url: str) -> str:
    """Normalize a URL so tracking params / fragments don't defeat dedup."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonicalize_url(url).encode()).hexdigest()[:16]


class SeenState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._state: dict[str, str] = {}
        if path.exists():
            try:
                self._state = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("Corrupt seen state at %s, starting fresh", path)

    def is_seen(self, url: str) -> bool:
        return url_hash(url) in self._state

    def mark_seen(self, url: str, when: date | None = None) -> None:
        when = when or datetime.now(tz=UTC).date()
        self._state[url_hash(url)] = when.isoformat()

    def prune(self, today: date | None = None) -> None:
        today = today or datetime.now(tz=UTC).date()
        cutoff = today - RETENTION
        self._state = {
            k: v for k, v in self._state.items() if date.fromisoformat(v) >= cutoff
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def filter_unseen(entries: list[FeedEntry], state: SeenState) -> list[FeedEntry]:
    """Drop already-seen entries and same-run duplicate URLs."""
    fresh: list[FeedEntry] = []
    run_seen: set[str] = set()
    for entry in entries:
        h = url_hash(entry.url)
        if h in run_seen or state.is_seen(entry.url):
            continue
        run_seen.add(h)
        fresh.append(entry)
    return fresh
