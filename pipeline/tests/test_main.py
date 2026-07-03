from __future__ import annotations

from digest.main import remap_clusters
from digest.models import FeedEntry, StoryCluster


def _entry(url: str) -> FeedEntry:
    return FeedEntry(title=f"Story at {url}", url=url, source="Test", topic="ai")


CANDIDATES = [_entry(f"https://example.com/{i}") for i in range(6)]


def _cluster(indices: list[int]) -> StoryCluster:
    return StoryCluster(entry_indices=indices, ai_relevant=True, significance=7, reason="test")


def test_remap_all_extractions_survive() -> None:
    winners = [CANDIDATES[i] for i in [1, 3, 5]]
    clusters = [_cluster([1]), _cluster([3, 5])]

    remapped = remap_clusters(clusters, CANDIDATES, winners)

    assert [c.entry_indices for c in remapped] == [[0], [1, 2]]


def test_remap_drops_failed_extraction_from_cluster() -> None:
    # Entry 3 failed extraction, so the extracted list shrinks and every
    # position after it shifts. The old index arithmetic pointed cluster 2 at
    # position 2 of a two-element list; URL matching gives the right answer.
    extracted = [CANDIDATES[1], CANDIDATES[5]]
    clusters = [_cluster([1]), _cluster([3, 5])]

    remapped = remap_clusters(clusters, CANDIDATES, extracted)

    assert [c.entry_indices for c in remapped] == [[0], [1]]


def test_remap_drops_cluster_when_all_members_fail() -> None:
    extracted = [CANDIDATES[1]]
    clusters = [_cluster([1]), _cluster([3])]

    remapped = remap_clusters(clusters, CANDIDATES, extracted)

    assert len(remapped) == 1
    assert remapped[0].entry_indices == [0]


def test_remap_empty_when_nothing_extracted() -> None:
    assert remap_clusters([_cluster([0])], CANDIDATES, []) == []
