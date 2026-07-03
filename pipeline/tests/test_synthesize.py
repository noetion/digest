from __future__ import annotations

import pytest

from digest.models import Digest, FeedEntry, StoryCluster
from digest.synthesize import (
    SYNTHESIS_SYSTEM_PROMPT,
    _dominant_domain,
    _pick_primary,
    attach_cluster_sources,
    capped_source_urls,
    scrub_digest,
)


def _entry(domain: str, words: int) -> FeedEntry:
    return FeedEntry(
        title=f"Story on {domain}",
        url=f"https://{domain}/article",
        source=domain,
        topic="ai",
        full_text=" ".join(["word"] * words),
    )


def _cluster(indices: list[int]) -> StoryCluster:
    return StoryCluster(entry_indices=indices, ai_relevant=True, significance=7, reason="t")


def test_dominant_domain_requires_repeat() -> None:
    entries = [_entry("a.com", 100), _entry("b.com", 100), _entry("c.com", 100)]
    clusters = [_cluster([0]), _cluster([1]), _cluster([2])]
    assert _dominant_domain(entries, clusters) is None


def test_dominant_domain_found_when_one_outlet_leads_multiple_stories() -> None:
    entries = [_entry("a.com", 100), _entry("a.com", 100), _entry("b.com", 100)]
    clusters = [_cluster([0]), _cluster([1]), _cluster([2])]
    assert _dominant_domain(entries, clusters) == "a.com"


def test_pick_primary_prefers_near_equal_alternate_outlet() -> None:
    dominant_member = _entry("a.com", 100)
    alternate = _entry("b.com", 80)  # >= 70% of the longest
    assert _pick_primary([dominant_member, alternate], "a.com") is alternate


def test_pick_primary_keeps_longest_when_alternate_is_too_thin() -> None:
    dominant_member = _entry("a.com", 100)
    alternate = _entry("b.com", 50)  # < 70% of the longest
    assert _pick_primary([dominant_member, alternate], "a.com") is dominant_member


def test_pick_primary_no_dominant_domain_takes_longest() -> None:
    members = [_entry("a.com", 100), _entry("b.com", 90)]
    assert _pick_primary(members, None) is members[0]


def test_scrub_digest_removes_em_dashes(sample_digest: Digest) -> None:
    sample_digest.intro = "New silicon \u2014 and it ships this quarter."
    sample_digest.stories[0].why_it_matters = "Cheaper inference\u2014full stop."

    scrubbed = scrub_digest(sample_digest)

    assert scrubbed.intro == "New silicon, and it ships this quarter."
    assert scrubbed.stories[0].why_it_matters == "Cheaper inference-full stop."
    dumped = scrubbed.model_dump_json()
    assert "\u2014" not in dumped


def test_scrub_digest_leaves_clean_text_alone(sample_digest: Digest) -> None:
    before = sample_digest.model_dump_json()
    assert before == scrub_digest(sample_digest).model_dump_json()


def test_attach_cluster_sources_assigns_from_clusters(sample_digest: Digest) -> None:
    entries = [
        FeedEntry(
            title="Primary",
            url="https://a.com/1",
            source="a.com",
            topic="ai",
        ),
        FeedEntry(
            title="Corroborating",
            url="https://b.com/2",
            source="b.com",
            topic="ai",
        ),
    ]
    clusters = [
        StoryCluster(entry_indices=[0, 1], ai_relevant=True, significance=8, reason="t"),
    ]
    sample_digest.stories = sample_digest.stories[:1]
    sample_digest.stories[0].source_urls = ["https://wrong.example/hallucinated"]

    attach_cluster_sources(sample_digest, entries, clusters)

    assert sample_digest.stories[0].source_urls == ["https://a.com/1"]


def test_capped_source_urls_returns_single_url() -> None:
    entries = [
        FeedEntry(
            title="Only",
            url="https://example.com/article",
            source="example.com",
            topic="ai",
        )
    ]
    assert capped_source_urls(entries, dominant=None) == ["https://example.com/article"]


def test_attach_cluster_sources_uses_single_url(sample_digest: Digest) -> None:
    entries = [
        FeedEntry(
            title=f"Story {i}",
            url=f"https://site{i}.com/article",
            source=f"site{i}.com",
            topic="ai",
            full_text="word " * (50 - i),
        )
        for i in range(5)
    ]
    clusters = [
        StoryCluster(entry_indices=list(range(5)), ai_relevant=True, significance=8, reason="t"),
    ]
    sample_digest.stories = sample_digest.stories[:1]

    attach_cluster_sources(sample_digest, entries, clusters)

    assert sample_digest.stories[0].source_urls == ["https://site0.com/article"]


def test_attach_cluster_sources_rejects_count_mismatch(sample_digest: Digest) -> None:
    entries = [
        FeedEntry(title="One", url="https://a.com/1", source="a.com", topic="ai"),
    ]
    clusters = [
        StoryCluster(entry_indices=[0], ai_relevant=True, significance=8, reason="t"),
    ]
    with pytest.raises(ValueError, match="3 stories for 1 clusters"):
        attach_cluster_sources(sample_digest, entries, clusters)


def test_system_prompt_bans_em_dashes() -> None:
    assert "em dash" in SYNTHESIS_SYSTEM_PROMPT.lower()
