from __future__ import annotations

from digest.models import Digest, FeedEntry, StoryCluster
from digest.synthesize import (
    SYNTHESIS_SYSTEM_PROMPT,
    _dominant_domain,
    _pick_primary,
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


def test_system_prompt_bans_em_dashes() -> None:
    assert "em dash" in SYNTHESIS_SYSTEM_PROMPT.lower()
