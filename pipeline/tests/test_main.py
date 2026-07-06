from __future__ import annotations

from unittest.mock import patch

from digest.main import cluster_member_urls, extract_selected_clusters, remap_clusters
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


def test_cluster_member_urls_from_remapped_only() -> None:
    winners = [CANDIDATES[1], CANDIDATES[5]]
    remapped = [_cluster([0]), _cluster([1])]
    assert cluster_member_urls(remapped, winners) == [
        "https://example.com/1",
        "https://example.com/5",
    ]


def _with_text(entry: FeedEntry) -> FeedEntry:
    return entry.model_copy(update={"full_text": f"Body for {entry.url}"})


def test_extract_backfill_promotes_next_ranked_cluster() -> None:
    ranked = [
        _cluster([0]),
        _cluster([1]),
        _cluster([2]),
        _cluster([3]),
        _cluster([4]),
        _cluster([5]),
    ]

    def fake_enrich(entries: list[FeedEntry], _max_words: int) -> list[FeedEntry]:
        return [_with_text(e) for e in entries if e.url != CANDIDATES[1].url]

    with patch("digest.main.enrich_with_full_text", side_effect=fake_enrich):
        winners, published = extract_selected_clusters(
            ranked, CANDIDATES, max_stories=5, max_words=1000
        )

    assert len(published) == 5
    published_urls = {winners[c.entry_indices[0]].url for c in published}
    assert CANDIDATES[1].url not in published_urls
    assert CANDIDATES[5].url in published_urls
    assert len(winners) == 5
