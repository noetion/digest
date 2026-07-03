from __future__ import annotations

from datetime import date
from pathlib import Path

from digest.dedupe import SeenState, canonicalize_url, filter_unseen
from digest.models import FeedEntry


def _entry(url: str) -> FeedEntry:
    return FeedEntry(title="t", url=url, source="s", topic="ai")


def test_canonicalize_strips_tracking_and_fragments() -> None:
    assert canonicalize_url(
        "https://Example.com/a/?utm_source=x&ref=y#section"
    ) == canonicalize_url("https://example.com/a")


def test_state_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    state = SeenState(path)
    state.mark_seen("https://example.com/a", date(2026, 7, 2))
    state.save()

    reloaded = SeenState(path)
    assert reloaded.is_seen("https://example.com/a")
    assert not reloaded.is_seen("https://example.com/b")


def test_prune_drops_old_entries(tmp_path: Path) -> None:
    state = SeenState(tmp_path / "seen.json")
    state.mark_seen("https://example.com/old", date(2026, 6, 1))
    state.mark_seen("https://example.com/new", date(2026, 7, 1))
    state.prune(today=date(2026, 7, 2))
    assert not state.is_seen("https://example.com/old")
    assert state.is_seen("https://example.com/new")


def test_filter_unseen_drops_seen_and_same_run_duplicates(tmp_path: Path) -> None:
    state = SeenState(tmp_path / "seen.json")
    state.mark_seen("https://example.com/seen")
    entries = [
        _entry("https://example.com/seen"),
        _entry("https://example.com/new"),
        _entry("https://example.com/new?utm_source=feed"),
    ]
    fresh = filter_unseen(entries, state)
    assert [e.url for e in fresh] == ["https://example.com/new"]


def test_corrupt_state_starts_fresh(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_text("{not json", encoding="utf-8")
    state = SeenState(path)
    assert not state.is_seen("https://example.com/a")


def test_utf16_state_loads_and_rewrites_as_utf8(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_bytes('{"abc123": "2026-07-02"}\n'.encode("utf-16"))
    state = SeenState(path)
    assert state._state == {"abc123": "2026-07-02"}
    state.save()
    assert path.read_bytes()[:1] == b"{"
    assert SeenState(path)._state == {"abc123": "2026-07-02"}
