from __future__ import annotations

from digest.models import FeedEntry


def test_preview_flags_link_only_hn_summary() -> None:
    entry = FeedEntry(
        title="GPT-5.6 Sol Ultra will be in Codex",
        url="https://news.ycombinator.com/item?id=1",
        source="Hacker News",
        topic="dev-tools",
        summary=(
            '<p><a href="https://x.com/haider1/status/123">https://x.com/haider1/status/123</a></p>'
        ),
    )
    preview = entry.preview()
    assert "No useful RSS preview" in preview
    assert "https://x.com" not in preview
