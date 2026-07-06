from __future__ import annotations

from digest.editorial import MIN_SIGNIFICANCE, select_clusters
from digest.models import ClusterGroup, FeedEntry, StoryCluster
from digest.triage import (
    SCORE_SYSTEM_PROMPT,
    merge_cluster_scores,
    normalize_cluster_groups,
)


def _entry(i: int, domain: str = "example.com", topic: str = "ai") -> FeedEntry:
    return FeedEntry(
        title=f"Story {i}",
        url=f"https://{domain}/article/{i}",
        source=domain,
        topic=topic,
    )


ENTRIES = [_entry(i, domain=f"outlet{i}.com") for i in range(8)]


def _cluster(
    indices: list[int], significance: int = 7, ai_relevant: bool = True
) -> StoryCluster:
    return StoryCluster(
        entry_indices=indices,
        ai_relevant=ai_relevant,
        significance=significance,
        reason="test",
    )


def _score_map(clusters: list[StoryCluster]) -> dict[int, StoryCluster]:
    return {c.entry_indices[0]: c for c in clusters if len(c.entry_indices) == 1}


def test_keeps_top_clusters_by_significance() -> None:
    raw = [_cluster([0], 5), _cluster([1], 9), _cluster([2], 7)]
    selected = select_clusters(raw, ENTRIES, max_stories=2)
    assert [c.significance for c in selected] == [9, 7]


def test_tier_a_reserved_before_tier_b() -> None:
    raw = [
        _cluster([0], 6),
        _cluster([1], 6),
        _cluster([2], 9),
        _cluster([3], 8),
        _cluster([4], 7),
    ]
    selected = select_clusters(raw, ENTRIES, max_stories=3)
    assert {c.significance for c in selected} == {9, 8, 7}


def test_score_five_kept_even_when_ai_relevant_false() -> None:
    raw = [_cluster([0], 9, ai_relevant=False), _cluster([1], 5)]
    selected = select_clusters(raw, ENTRIES, max_stories=5)
    assert [c.entry_indices for c in selected] == [[0], [1]]


def test_tier_c_ai_relevant_false_dropped_at_four() -> None:
    raw = [_cluster([0], 4, ai_relevant=False), _cluster([1], 5)]
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
    assert [c.entry_indices for c in selected] == [[0]]


def test_dev_tools_wins_tie_over_policy() -> None:
    entries = [
        FeedEntry(title="Policy story", url="https://a", source="A", topic="policy"),
        FeedEntry(title="Dev tools story", url="https://b", source="B", topic="dev-tools"),
    ]
    raw = [_cluster([0], 6), _cluster([1], 6)]
    selected = select_clusters(raw, entries, max_stories=1)
    assert selected[0].entry_indices == [1]


def test_score_prompt_targets_builder_tiers() -> None:
    assert "Tier A" in SCORE_SYSTEM_PROMPT
    assert "Codex" in SCORE_SYSTEM_PROMPT
    assert "FULL 1-10" in SCORE_SYSTEM_PROMPT
    assert "platform-scale vendors" in SCORE_SYSTEM_PROMPT
    assert "Microsoft, Google, Meta, Amazon" in SCORE_SYSTEM_PROMPT
    assert "production ML" not in SCORE_SYSTEM_PROMPT or "agent orchestration" in SCORE_SYSTEM_PROMPT


def test_normalize_cluster_groups_fills_missing_indices() -> None:
    groups = [ClusterGroup(entry_indices=[1, 2], event="shared")]
    assert normalize_cluster_groups(groups, 4) == [[1, 2], [0], [3]]


def test_merge_keeps_duplicate_group_with_best_member_score() -> None:
    groups = [ClusterGroup(entry_indices=[0, 1], event="Mechanical Turk sunset")]
    scored = _score_map([_cluster([0], 6), _cluster([1], 9)])
    merged = merge_cluster_scores(groups, scored, n_entries=2)
    assert len(merged) == 1
    assert merged[0].entry_indices == [0, 1]
    assert merged[0].significance == 9


def test_merge_dissolves_oversized_group_into_singletons() -> None:
    groups = [ClusterGroup(entry_indices=[0, 1, 2, 3, 4], event="AI news bucket")]
    scored = _score_map(
        [
            _cluster([0], 3, ai_relevant=False),
            _cluster([1], 8),
            _cluster([4], 7),
        ]
    )
    merged = merge_cluster_scores(groups, scored, n_entries=5)
    assert [c.entry_indices for c in merged] == [[0], [1], [4]]


def test_merge_uses_best_scorer_metadata() -> None:
    groups = [ClusterGroup(entry_indices=[0, 1], event="shared")]
    scored = {
        0: _cluster([0], 5, ai_relevant=True),
        1: _cluster([1], 8, ai_relevant=True),
    }
    merged = merge_cluster_scores(groups, scored, n_entries=2)
    assert merged[0].significance == 8
    assert merged[0].reason == "test"
