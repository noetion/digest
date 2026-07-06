from __future__ import annotations

from digest.models import FeedEntry, StoryCluster
from digest.triage import (
    MAX_CLUSTER_MEMBERS,
    MIN_SIGNIFICANCE,
    TRIAGE_SYSTEM_PROMPT,
    replace_repriced_clusters,
    select_clusters,
    split_oversized_clusters,
)


def _entry(i: int, domain: str = "example.com") -> FeedEntry:
    return FeedEntry(
        title=f"Story {i}",
        url=f"https://{domain}/article/{i}",
        source=domain,
        topic="ai",
    )


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


def test_non_ai_clusters_are_dropped() -> None:
    raw = [_cluster([0], 9, ai_relevant=False), _cluster([1], 5)]
    selected = select_clusters(raw, ENTRIES, max_stories=5)
    assert [c.entry_indices for c in selected] == [[1]]


def test_non_ai_never_fills_slots() -> None:
    raw = [
        _cluster([0], 9, ai_relevant=False),
        _cluster([1], 4),
        _cluster([2], 5),
    ]
    selected = select_clusters(raw, ENTRIES, max_stories=2)
    assert [c.entry_indices for c in selected] == [[2], [1]]


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
    assert [c.entry_indices for c in selected] == [[0]]


def test_prompt_mentions_ai_relevant_gate() -> None:
    assert "ai_relevant" in TRIAGE_SYSTEM_PROMPT


def test_prompt_forbids_theme_clustering() -> None:
    assert "Never group articles because they share" in TRIAGE_SYSTEM_PROMPT
    assert "four entry indices" in TRIAGE_SYSTEM_PROMPT


def test_prompt_targets_builder_mix_with_tier_b_context() -> None:
    assert "Tier A" in TRIAGE_SYSTEM_PROMPT
    assert "Tier B" in TRIAGE_SYSTEM_PROMPT
    assert "true ONLY for Tier A or Tier B" in TRIAGE_SYSTEM_PROMPT
    assert "Microsoft, Amazon" in TRIAGE_SYSTEM_PROMPT
    assert "smart glasses" in TRIAGE_SYSTEM_PROMPT
    assert "mostly A" in TRIAGE_SYSTEM_PROMPT


def test_oversized_cluster_flags_repriced_indices_not_inherited_metadata() -> None:
    mega = _cluster(list(range(MAX_CLUSTER_MEMBERS + 2)), significance=4, ai_relevant=False)
    small = _cluster([7], significance=8)
    kept, repriced = split_oversized_clusters([small, mega])
    assert kept == [small]
    assert repriced == frozenset(range(MAX_CLUSTER_MEMBERS + 2))


def test_replace_repriced_clusters_swaps_bucket_singletons() -> None:
    repriced = frozenset({0, 1, 2})
    bucket_singletons = [
        _cluster([i], significance=4, ai_relevant=False) for i in repriced
    ]
    replacements = [_cluster([0], significance=8), _cluster([2], significance=6)]
    merged = replace_repriced_clusters(bucket_singletons, repriced, replacements)
    assert [c.entry_indices for c in merged] == [[0], [2]]


def test_split_leaves_small_clusters_alone() -> None:
    small = _cluster([0, 1, 2], significance=7)
    kept, repriced = split_oversized_clusters([small])
    assert kept == [small]
    assert repriced == frozenset()
