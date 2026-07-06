from __future__ import annotations

from digest.editorial import (
    TIER_A_MIN,
    TIER_B_MIN,
    MAJOR_WORKFORCE_SCORE_FLOOR,
    effective_significance,
    editorial_family,
    editorial_geo_bucket,
    editorial_raw_significance,
    editorial_tier,
    is_agent_demo_stunt,
    is_builder_relevant,
    is_consumer_beta_noise,
    is_consumer_hardware_noise,
    is_specific_major_workforce_event,
    rank_selection_candidates,
    select_clusters,
)
from digest.models import FeedEntry, StoryCluster


def _cluster(
    indices: list[int], significance: int = 7, ai_relevant: bool = True
) -> StoryCluster:
    return StoryCluster(
        entry_indices=indices,
        ai_relevant=ai_relevant,
        significance=significance,
        reason="test",
    )


def _entry(title: str, topic: str = "ai", source: str = "A") -> FeedEntry:
    return FeedEntry(
        title=title,
        url=f"https://{source}/a",
        source=source,
        topic=topic,
    )


def test_editorial_tiers() -> None:
    assert editorial_tier(9) == "A"
    assert editorial_tier(8) == "A"
    assert editorial_tier(7) == "B"
    assert editorial_tier(5) == "B"
    assert editorial_tier(4) == "C"


def test_relevance_from_score_not_llm_flag_for_tier_b() -> None:
    entry = FeedEntry(title="x", url="https://a", source="A", topic="ai")
    assert is_builder_relevant(_cluster([0], TIER_B_MIN, ai_relevant=False), [entry])
    assert is_builder_relevant(_cluster([0], TIER_A_MIN, ai_relevant=False), [entry])


def test_relevance_at_four_requires_ai_relevant() -> None:
    entry = FeedEntry(title="x", url="https://a", source="A", topic="ai")
    assert not is_builder_relevant(_cluster([0], 4, ai_relevant=False), [entry])
    assert is_builder_relevant(_cluster([0], 4, ai_relevant=True), [entry])


def test_consumer_siri_beta_is_noise() -> None:
    title = "You can now customize Siri's pace and expressivity in the latest iOS 27 beta"
    assert is_consumer_beta_noise(title)
    entry = _entry(title)
    assert not is_builder_relevant(_cluster([0], 7), [entry])


def test_effective_significance_boosts_workforce() -> None:
    entry = _entry("Microsoft lays off nearly 5000 employees")
    cluster = _cluster([0], 7)
    assert effective_significance(cluster, [entry]) == 8


def test_microsoft_beats_siri_when_both_score_seven() -> None:
    entries = [
        _entry(
            "You can now customize Siri's pace and expressivity in the latest iOS 27 beta",
        ),
        _entry("Microsoft lays off nearly 5000 employees across Xbox"),
        _entry("Tencent releases Hy3 open-source model", "ai"),
    ]
    raw = [_cluster([0], 7), _cluster([1], 7), _cluster([2], 7)]
    selected = select_clusters(raw, entries, max_stories=2)
    assert [c.entry_indices[0] for c in selected] == [1, 2]


def test_workforce_family_loose_match() -> None:
    assert editorial_family("Microsoft lays off nearly 5000 employees") == "workforce"
    assert editorial_family("The running list: major tech layoffs in 2026") == "workforce"


def test_regulatory_commentary_family_loose_match() -> None:
    title = (
        "UK regulator warns of arms race to keep up with AI use in financial services"
    )
    assert editorial_family(title) == "regulatory_commentary"


def test_product_policy_not_regulatory_commentary() -> None:
    title = "If you use Google, you're training its AI. Here's how to opt out."
    assert editorial_family(title) is None


def test_open_model_not_capped() -> None:
    assert editorial_family("Tencent releases Hy3 open-source model") is None
    assert editorial_family("GPT-5.6 Sol Ultra will be in Codex") is None


def test_select_caps_workforce_prefers_specific_layoff() -> None:
    entries = [
        _entry("Microsoft lays off nearly 5000 employees across Xbox", "big-tech"),
        _entry("The running list: major tech layoffs in 2026 where employers cited AI"),
        _entry("Tencent releases Hy3 open-source model", "ai"),
    ]
    raw = [
        _cluster([0], 8),
        _cluster([1], 7),
        _cluster([2], 7),
    ]
    selected = select_clusters(raw, entries, max_stories=2)
    assert [c.entry_indices[0] for c in selected] == [0, 2]


def test_select_allows_fca_and_google_opt_out() -> None:
    entries = [
        _entry(
            "UK regulator warns of arms race to keep up with AI in financial services",
            "policy",
            "ars.com",
        ),
        _entry(
            "If you use Google, you're training its AI. Here's how to opt out.",
            "big-tech",
            "tc.com",
        ),
        _entry("Tencent releases Hy3 open-source model", "ai", "decoder.com"),
    ]
    raw = [_cluster([0], 7), _cluster([1], 6), _cluster([2], 8)]
    selected = select_clusters(raw, entries, max_stories=3)
    assert {c.entry_indices[0] for c in selected} == {0, 1, 2}


def test_select_caps_two_regulatory_commentary_stories() -> None:
    entries = [
        _entry(
            "UK regulator warns of arms race to keep up with AI in financial services",
            "policy",
        ),
        _entry(
            "EU regulators say they need more powers to keep up with AI in banking",
            "policy",
        ),
        _entry("Tencent releases Hy3 open-source model", "ai"),
    ]
    raw = [_cluster([0], 7), _cluster([1], 7), _cluster([2], 8)]
    selected = select_clusters(raw, entries, max_stories=2)
    assert len(selected) == 2
    assert 2 in selected[0].entry_indices or 2 in selected[1].entry_indices
    families = sum(1 for c in selected if c.entry_indices[0] in (0, 1))
    assert families == 1


def test_amd_dev_kit_is_consumer_hardware_noise() -> None:
    title = "AMD Ryzen AI Halo – $4k AI Dev Kit"
    assert is_consumer_hardware_noise(title)
    entry = _entry(title, "chips")
    assert not is_builder_relevant(_cluster([0], 9), [entry])


def test_datacenter_gpu_not_consumer_hardware() -> None:
    title = "NVIDIA Blackwell datacenter GPU for training clusters"
    assert not is_consumer_hardware_noise(title)


def test_expedia_production_ml_beats_amd_in_selection() -> None:
    entries = [
        _entry("Microsoft lays off nearly 5000 employees across Xbox", "big-tech", "tc.com"),
        _entry("AMD Ryzen AI Halo – $4k AI Dev Kit", "chips", "hn.com"),
        _entry("Tencent releases Hy3 open-source model", "ai", "decoder.com"),
        _entry(
            "What billions of AI predictions taught Expedia before the age of AI agents",
            "ai",
            "vb.com",
        ),
        _entry("Zhipu AI launches ZCode coding agent", "dev-tools", "decoder2.com"),
    ]
    raw = [
        _cluster([0], 9),
        _cluster([1], 9),
        _cluster([2], 8),
        _cluster([3], 7),
        _cluster([4], 8),
    ]
    selected = select_clusters(raw, entries, max_stories=4)
    titles = [entries[c.entry_indices[0]].title for c in selected]
    assert "AMD Ryzen AI Halo" not in " ".join(titles)
    assert any("Expedia" in t for t in titles)


def test_production_ml_effective_significance_boost() -> None:
    title = "What billions of AI predictions taught Expedia before the age of AI agents"
    entry = _entry(title)
    cluster = _cluster([0], 6)
    assert effective_significance(cluster, [entry]) == 7


def test_rank_selection_candidates_returns_reserve_depth() -> None:
    entries = [_entry(f"Story {i}", "ai", source=f"outlet{i}.com") for i in range(10)]
    raw = [_cluster([i], 6) for i in range(10)]
    ranked = rank_selection_candidates(raw, entries, max_candidates=8)
    assert len(ranked) == 8


def test_geo_bucket_matches_major_chinese_vendors() -> None:
    assert editorial_geo_bucket("Tencent releases Hy3 open-source model") == "asia_vendor"
    assert editorial_geo_bucket("Microsoft lays off nearly 5000 employees") is None


def test_geo_cap_limits_asia_vendor_stories() -> None:
    entries = [
        _entry("Tencent releases Hy3 open-source model", "ai", "tencent.com"),
        _entry("Zhipu AI launches ZCode coding agent", "dev-tools", "zhipu.com"),
        _entry("Baidu publishes Unlimited OCR model", "ai", "baidu.com"),
        _entry("Microsoft lays off nearly 5000 employees", "big-tech", "tc.com"),
    ]
    raw = [_cluster([0], 8), _cluster([1], 8), _cluster([2], 8), _cluster([3], 8)]
    selected = select_clusters(raw, entries, max_stories=3)
    asia = sum(
        1
        for c in selected
        if editorial_geo_bucket(entries[c.entry_indices[0]].title) == "asia_vendor"
    )
    assert asia <= 2
    assert any(c.entry_indices[0] == 3 for c in selected)


def test_meta_analysis_demoted_in_ranking() -> None:
    entries = [
        _entry(
            "GPT-4's dominance lasted a year while top models barely survive seven weeks",
            "ai",
            "decoder.com",
        ),
        _entry(
            "Microsoft lays off nearly 5000 employees across Xbox",
            "big-tech",
            "tc.com",
        ),
    ]
    raw = [_cluster([0], 8), _cluster([1], 8)]
    selected = select_clusters(raw, entries, max_stories=1)
    assert selected[0].entry_indices == [1]


def test_source_cap_limits_same_outlet() -> None:
    entries = [_entry(f"Story {i}", "the-decoder.com", "ai") for i in range(4)]
    raw = [_cluster([i], 8) for i in range(4)]
    selected = select_clusters(raw, entries, max_stories=4)
    assert len(selected) == 2


def test_source_cap_two_frees_slot_for_other_outlet() -> None:
    entries = [
        _entry("Decoder story A", "ai", "the-decoder.com"),
        _entry("Decoder story B", "ai", "the-decoder.com"),
        _entry("Decoder story C", "ai", "the-decoder.com"),
        _entry("Vercel CEO on models vs agents", "dev-tools", "techcrunch.com"),
    ]
    raw = [_cluster([i], 8) for i in range(4)]
    selected = select_clusters(raw, entries, max_stories=3)
    titles = [entries[c.entry_indices[0]].title for c in selected]
    assert sum("Decoder" in t for t in titles) == 2
    assert any("Vercel" in t for t in titles)


def test_specific_major_workforce_event_matches_platform_vendors() -> None:
    assert is_specific_major_workforce_event(
        "Microsoft lays off nearly 5000 employees across Xbox"
    )
    assert is_specific_major_workforce_event(
        "Google cuts 1200 roles in cloud division reorg"
    )
    assert is_specific_major_workforce_event("Meta lays off 4000 workers")
    assert not is_specific_major_workforce_event(
        "Every major tech layoff in 2026 that has name-checked AI"
    )
    assert not is_specific_major_workforce_event(
        "StartupCo lays off 40 employees"
    )


def test_major_workforce_floor_when_nano_under_scores() -> None:
    ms = _entry("Microsoft lays off nearly 5000 employees across Xbox", "big-tech")
    google = _entry("Google cuts 1200 roles in cloud reorg", "big-tech")
    for entry in (ms, google):
        cluster = _cluster([0], 3, ai_relevant=False)
        assert editorial_raw_significance(cluster, [entry]) == MAJOR_WORKFORCE_SCORE_FLOOR
        assert is_builder_relevant(cluster, [entry])
        assert effective_significance(cluster, [entry]) == MAJOR_WORKFORCE_SCORE_FLOOR + 1


def test_layoff_roundup_not_floored_when_under_scored() -> None:
    entry = _entry("Every major tech layoff in 2026 that has name-checked AI")
    cluster = _cluster([0], 3, ai_relevant=False)
    assert editorial_raw_significance(cluster, [entry]) == 3
    assert not is_builder_relevant(cluster, [entry])


def test_under_scored_major_workforce_can_enter_selection() -> None:
    entries = [
        _entry("Microsoft lays off nearly 5000 employees across Xbox", "big-tech", "tc.com"),
    ]
    raw = [_cluster([0], 3, ai_relevant=False)]
    selected = select_clusters(raw, entries, max_stories=1)
    assert selected[0].entry_indices == [0]


def test_expedia_beats_fca_regulatory_commentary_at_same_score() -> None:
    """Mirrors July 6 slot-5 competition: production ML over regulator commentary."""
    entries = [
        _entry("Tencent releases Hy3 open-source model under Apache 2.0", "ai", "decoder.com"),
        _entry("Zhipu AI launches ZCode coding agent", "dev-tools", "decoder.com"),
        _entry(
            "If you use Google, you're training its AI. Here's how to opt out.",
            "policy",
            "techcrunch.com",
        ),
        _entry("Microsoft lays off nearly 5000 employees across Xbox", "big-tech", "tc.com"),
        _entry(
            "UK regulator warns of arms race to keep up with AI in financial services",
            "policy",
            "ars.com",
        ),
        _entry(
            "What billions of AI predictions taught Expedia before the age of AI agents",
            "ai",
            "vb.com",
        ),
    ]
    raw = [
        _cluster([0], 9),
        _cluster([1], 9),
        _cluster([2], 9),
        _cluster([3], 7),
        _cluster([4], 8),
        _cluster([5], 7),
    ]
    selected = select_clusters(raw, entries, max_stories=5)
    titles = [entries[c.entry_indices[0]].title for c in selected]
    assert any("Expedia" in t for t in titles)
    assert not any("arms race" in t for t in titles)


def test_agent_demo_stunt_detected() -> None:
    title = (
        "Claude Code and Fable 5 ported the 2003 PC game Command & Conquer "
        "to native iOS in a few hours"
    )
    assert is_agent_demo_stunt(title)


def test_expedia_beats_game_port_demo_at_same_score() -> None:
    entries = [
        _entry(
            "Claude Code and Fable 5 ported Command & Conquer to native iOS in a few hours",
            "ai",
            "decoder.com",
        ),
        _entry(
            "What billions of AI predictions taught Expedia before the age of AI agents",
            "ai",
            "vb.com",
        ),
        _entry("Tencent releases Hy3 open-source model", "ai", "tencent.com"),
    ]
    raw = [_cluster([0], 8), _cluster([1], 8), _cluster([2], 8)]
    selected = select_clusters(raw, entries, max_stories=2)
    titles = [entries[c.entry_indices[0]].title for c in selected]
    assert any("Expedia" in t for t in titles)
    assert not any("Command & Conquer" in t for t in titles)
