from __future__ import annotations

from digest.models import FeedEntry, StoryCluster
from digest.triage import MIN_SIGNIFICANCE, TRIAGE_SYSTEM_PROMPT, select_clusters


def _entry(i: int) -> FeedEntry:
    return FeedEntry(title=f"Story {i}", url=f"https://example.com/{i}", source="Test", topic="ai")


ENTRIES = [_entry(i) for i in range(8)]


def _cluster(
    indices: list[int], significance: int = 7, ai_relevant: bool = True
) -> StoryCluster:
    return StoryCluster(
        entry_indices=indices,
        ai_relevant=ai_relevant,
        significance=significance,
        reason="test",
    )


def test_keeps_top_clusters_by_significance() -> None:
    raw = [_cluster([0], 5), _cluster([1], 9), _cluster([2], 7)]
    selected = select_clusters(raw, ENTRIES, max_stories=2)
    assert [c.significance for c in selected] == [9, 7]


def test_drops_non_ai_relevant_even_when_high_scoring() -> None:
    raw = [_cluster([0], 9, ai_relevant=False), _cluster([1], 5)]
    selected = select_clusters(raw, ENTRIES, max_stories=5)
    assert [c.entry_indices for c in selected] == [[1]]


def test_enforces_significance_floor() -> None:
    raw = [_cluster([0], MIN_SIGNIFICANCE - 1), _cluster([1], MIN_SIGNIFICANCE)]
    selected = select_clusters(raw, ENTRIES, max_stories=5)
    assert [c.entry_indices for c in selected] == [[1]]


def test_short_digest_when_news_day_is_thin() -> None:
    raw = [_cluster([0], 2), _cluster([1], 3)]
    assert select_clusters(raw, ENTRIES, max_stories=5) == []


def test_invalid_and_duplicate_indices_are_dropped() -> None:
    raw = [_cluster([0, 99], 8), _cluster([0], 7)]
    selected = select_clusters(raw, ENTRIES, max_stories=5)
    # 99 is out of range; index 0 belongs to the first (higher-scored) cluster.
    assert [c.entry_indices for c in selected] == [[0]]


def test_prompt_mentions_ai_relevant_gate() -> None:
    assert "ai_relevant" in TRIAGE_SYSTEM_PROMPT
