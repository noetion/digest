from __future__ import annotations

import pytest

from digest.models import Digest, FeedEntry, StoryCluster
from digest.synthesize import (
    SYNTHESIS_SYSTEM_PROMPT,
    _dominant_domain,
    _pick_primary,
    attach_cluster_sources,
    source_urls_for_story,
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
    assert scrubbed.stories[0].why_it_matters == "Cheaper inference, full stop."
    dumped = scrubbed.model_dump_json()
    assert "\u2014" not in dumped


def test_scrub_digest_fixes_unspaced_em_dash_before_digit(sample_digest: Digest) -> None:
    sample_digest.stories[0].outlook = (
        "Use the stated scale\u20146 million daily deployments as the baseline."
    )

    scrubbed = scrub_digest(sample_digest)

    assert "scale: 6 million" in scrubbed.stories[0].outlook
    assert "scale-6" not in scrubbed.stories[0].outlook


def test_scrub_digest_fixes_sub_memory_shorthand(sample_digest: Digest) -> None:
    sample_digest.stories[0].why_it_matters = (
        "Hy3's sub\u2014300GB FP8 footprint lowers serving memory."
    )

    scrubbed = scrub_digest(sample_digest)

    assert "under 300GB" in scrubbed.stories[0].why_it_matters
    assert "sub: 300" not in scrubbed.stories[0].why_it_matters


def test_scrub_digest_fixes_apache_license_em_dash(sample_digest: Digest) -> None:
    sample_digest.stories[0].headline = (
        "Tencent releases Apache\u20142.0 Hy3 open-weight model"
    )

    scrubbed = scrub_digest(sample_digest)

    assert "Apache 2.0" in scrubbed.stories[0].headline
    assert "Apache: 2.0" not in scrubbed.stories[0].headline


def test_scrub_digest_fixes_apache_colon_artifact(sample_digest: Digest) -> None:
    sample_digest.stories[0].headline = "Tencent releases Apache: 2.0 Hy3 model"

    scrubbed = scrub_digest(sample_digest)

    assert scrubbed.stories[0].headline == "Tencent releases Apache 2.0 Hy3 model"


def test_scrub_digest_fixes_unspaced_em_dash_between_words(sample_digest: Digest) -> None:
    sample_digest.stories[0].what_happened = (
        "Expedia added Agentic Release tollgates\u2014recommended checks in the SDLC."
    )

    scrubbed = scrub_digest(sample_digest)

    assert "tollgates, recommended" in scrubbed.stories[0].what_happened


def test_scrub_digest_fixes_glued_qualifier_hyphens(sample_digest: Digest) -> None:
    sample_digest.stories[0].what_happened = (
        "Expedia added tollgates-recommended checks and rollback controls-practices."
    )

    scrubbed = scrub_digest(sample_digest)

    assert "tollgates, recommended" in scrubbed.stories[0].what_happened
    assert "controls, practices" in scrubbed.stories[0].what_happened


def test_scrub_digest_preserves_en_dashes_in_compounds(sample_digest: Digest) -> None:
    sample_digest.stories[0].headline = "ZCode: GLM-5.2\u2013based coding agent"

    scrubbed = scrub_digest(sample_digest)

    assert scrubbed.stories[0].headline == "ZCode: GLM-5.2\u2013based coding agent"


def test_scrub_digest_leaves_clean_text_alone(sample_digest: Digest) -> None:
    before = sample_digest.model_dump_json()
    assert before == scrub_digest(sample_digest).model_dump_json()


def test_attach_cluster_sources_assigns_from_clusters(sample_digest: Digest) -> None:
    entries = [
        FeedEntry(
            title="Tencent releases Hy3 open-source model",
            url="https://a.com/1",
            source="a.com",
            topic="ai",
        ),
        FeedEntry(
            title="Tencent Apache-licensed Hy3 takes on GLM-5.2",
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

    assert sample_digest.stories[0].source_urls == ["https://a.com/1", "https://b.com/2"]


def test_source_urls_for_story_single_article() -> None:
    entries = [
        FeedEntry(
            title="Only",
            url="https://example.com/article",
            source="example.com",
            topic="ai",
            full_text="word " * 50,
        )
    ]
    assert source_urls_for_story(entries, dominant=None) == ["https://example.com/article"]


def test_source_urls_for_story_two_articles() -> None:
    entries = [
        FeedEntry(
            title="Primary",
            url="https://a.com/1",
            source="a.com",
            topic="ai",
            full_text="word " * 50,
        ),
        FeedEntry(
            title="Also",
            url="https://b.com/2",
            source="b.com",
            topic="ai",
            full_text="word " * 40,
        ),
    ]
    assert source_urls_for_story(entries, dominant=None) == [
        "https://a.com/1",
        "https://b.com/2",
    ]


def test_source_urls_for_story_caps_at_three() -> None:
    entries = [
        FeedEntry(
            title=f"Story {i}",
            url=f"https://{'ieee.org' if i == 0 else f'outlet{i}.com'}/article",
            source="ieee.org" if i == 0 else f"outlet{i}.com",
            topic="ai",
            full_text=" ".join(["word"] * (100 - i * 10)),
        )
        for i in range(6)
    ]
    urls = source_urls_for_story(entries, dominant=None)
    assert len(urls) == 3
    assert "https://ieee.org/article" in urls


def test_attach_cluster_sources_caps_mega_cluster(sample_digest: Digest) -> None:
    entries = [
        FeedEntry(
            title=(
                "Tencent releases Hy3 open-source model"
                if i == 0
                else f"Coverage: Tencent's Hy3 model update from outlet {i}"
            ),
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

    assert len(sample_digest.stories[0].source_urls) == 3


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
    assert "en dashes" in SYNTHESIS_SYSTEM_PROMPT.lower()
    assert "fine in numeric ranges" in SYNTHESIS_SYSTEM_PROMPT.lower()
    assert "model-agent split" in SYNTHESIS_SYSTEM_PROMPT
    assert "agent coding pushes" in SYNTHESIS_SYSTEM_PROMPT
    assert "Never start outlook with" not in SYNTHESIS_SYSTEM_PROMPT
    assert "what to look for next" in SYNTHESIS_SYSTEM_PROMPT.lower()
    assert "bifurcat" in SYNTHESIS_SYSTEM_PROMPT.lower()
    assert "Reflect the stories actually" in SYNTHESIS_SYSTEM_PROMPT
    assert "Every story must appear in the intro" in SYNTHESIS_SYSTEM_PROMPT
    assert "Three platform moves today matter" in SYNTHESIS_SYSTEM_PROMPT
    assert "Fiscal-year 2027" in SYNTHESIS_SYSTEM_PROMPT
    assert "Have marketing and legal" in SYNTHESIS_SYSTEM_PROMPT
    assert "plain english" in SYNTHESIS_SYSTEM_PROMPT.lower()
    assert "recognizable proper noun" in SYNTHESIS_SYSTEM_PROMPT
    assert "not a vague summary" in SYNTHESIS_SYSTEM_PROMPT
    assert "quiet tension" in SYNTHESIS_SYSTEM_PROMPT
    assert "what CHANGED today" in SYNTHESIS_SYSTEM_PROMPT
