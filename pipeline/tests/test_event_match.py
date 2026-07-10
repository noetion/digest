from __future__ import annotations

from digest.event_match import (
    assert_unique_event_clusters,
    cluster_is_coherent,
    cluster_should_merge_with,
    coerce_coherent_clusters,
    entries_same_event,
    merge_duplicate_event_clusters,
    refine_cluster_groups,
    split_incoherent_clusters,
    titles_same_event,
)
from digest.models import ClusterGroup, FeedEntry, StoryCluster


def _entry(
    title: str,
    url: str = "https://example.com/a",
    topic: str = "ai",
    summary: str = "",
) -> FeedEntry:
    return FeedEntry(title=title, url=url, source="Example", topic=topic, summary=summary)


def test_hy3_headlines_are_same_event() -> None:
    decoder = "Tencent releases Hy3 open-source model that allegedly matches models up to five times its active size"
    vb = "Tencent's Apache-licensed Hy3 takes on GLM-5.2 at half the size and wins everywhere except coding"
    assert titles_same_event(decoder, vb)


def test_mechanical_turk_headlines_are_same_event() -> None:
    a = "Amazon sunsets Mechanical Turk, the original artificial artificial intelligence"
    b = "Amazon will stop accepting new customers for Mechanical Turk"
    assert titles_same_event(a, b)


def test_unrelated_microsoft_and_regulator_are_not_same_event() -> None:
    ms = "Microsoft lays off nearly 5000 employees across Xbox and commercial sales"
    fca = "UK regulator warns of arms race to keep up with AI use in financial services"
    assert not titles_same_event(ms, fca)


def test_claude_stories_do_not_merge() -> None:
    tracker = "Secret Claude tracker shocks users after Anthropic anti-surveillance stance"
    cnc = "Claude Code and Fable 5 ported Command and Conquer to native iOS in a few hours"
    zcode = "Zhipu AI launches ZCode to challenge Claude Code and OpenAI Codex at a fraction of the cost"
    assert not titles_same_event(tracker, cnc)
    assert not titles_same_event(tracker, zcode)
    assert not titles_same_event(cnc, zcode)


def test_refine_merges_split_hy3_groups() -> None:
    entries = [
        _entry(
            "Tencent releases Hy3 open-source model",
            "https://the-decoder.com/hy3",
        ),
        _entry(
            "Tencent's Apache-licensed Hy3 takes on GLM-5.2",
            "https://venturebeat.com/hy3",
        ),
        _entry("Microsoft layoffs", "https://techcrunch.com/ms"),
    ]
    groups = [
        ClusterGroup(entry_indices=[0], event="Tencent Hy3 open source"),
        ClusterGroup(entry_indices=[1], event="Hy3 enterprise deployment"),
        ClusterGroup(entry_indices=[2], event="Microsoft layoffs"),
    ]
    refined = refine_cluster_groups(groups, entries, max_members=4)
    assert len(refined) == 2
    hy3 = next(g for g in refined if 0 in g.entry_indices)
    assert hy3.entry_indices == [0, 1]


def test_split_incoherent_cluster() -> None:
    entries = [
        _entry("Secret Claude tracker shocks users", "https://a"),
        _entry("Claude Code ported C&C to iOS", "https://b"),
        _entry("Zhipu ZCode challenges Codex", "https://c"),
    ]
    bad = StoryCluster(
        entry_indices=[0, 1, 2],
        ai_relevant=True,
        significance=6,
        reason="test",
    )
    assert not cluster_is_coherent(bad, entries)
    split = split_incoherent_clusters([bad], entries)
    assert len(split) == 3
    assert [c.entry_indices for c in split] == [[0], [1], [2]]


def test_unrelated_fca_and_hy3_are_not_same_event() -> None:
    fca = "UK regulator warns of arms race to keep up with AI use in financial services"
    hy3 = "Tencent releases Hy3 open-source model that allegedly matches models up to five times its active size"
    assert not titles_same_event(fca, hy3)


def test_primary_research_and_coverage_are_same_event() -> None:
    primary = (
        "Anthropic finds a small, reportable internal workspace in Claude "
        "using a J-lens on global workspace dynamics"
    )
    coverage = (
        "Coverage: Anthropic's J-lens paper reframes safety monitoring "
        "inside Claude's silent workspace"
    )
    assert titles_same_event(primary, coverage)


def test_refine_merges_primary_and_coverage_groups() -> None:
    entries = [
        _entry(
            "Anthropic finds a reportable internal workspace in Claude using a J-lens",
            "https://anthropic.com/research/global-workspace",
        ),
        _entry(
            "Coverage: Anthropic's J-lens paper reframes safety monitoring inside Claude",
            "https://venturebeat.com/anthropic-j-lens",
        ),
        _entry("Microsoft layoffs", "https://techcrunch.com/ms"),
    ]
    groups = [
        ClusterGroup(entry_indices=[0], event="Anthropic J-lens"),
        ClusterGroup(entry_indices=[1], event="Coverage Anthropic J-lens"),
        ClusterGroup(entry_indices=[2], event="Microsoft layoffs"),
    ]
    refined = refine_cluster_groups(groups, entries, max_members=4)
    assert len(refined) == 2
    anthropic = next(g for g in refined if 0 in g.entry_indices)
    assert anthropic.entry_indices == [0, 1]


def test_assert_unique_event_clusters_raises_on_duplicates() -> None:
    entries = [
        _entry("Anthropic J-lens workspace in Claude", "https://anthropic.com/a"),
        _entry("Coverage: Anthropic J-lens workspace in Claude", "https://vb.com/a"),
    ]
    clusters = [
        StoryCluster(entry_indices=[0], ai_relevant=True, significance=8, reason="a"),
        StoryCluster(entry_indices=[1], ai_relevant=True, significance=7, reason="b"),
    ]
    try:
        assert_unique_event_clusters(clusters, entries)
    except ValueError as exc:
        assert "Duplicate event" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_production_anthropic_titles_merge_via_entry_match() -> None:
    primary = _entry(
        "A global workspace in language models",
        "https://www.anthropic.com/research/global-workspace",
        summary="Anthropic introduces the J-space and J-lens inside Claude.",
    )
    coverage = _entry(
        "Anthropic's new J-lens reveals a silent workspace inside Claude",
        "https://venturebeat.com/technology/anthropics-new-j-lens-reveals-a-silent-workspace-inside-claude-that-mirrors-a-leading-theory-of-consciousness",
    )
    assert not titles_same_event(primary.title, coverage.title)
    assert entries_same_event(primary, coverage)


def test_refine_merges_production_anthropic_groups() -> None:
    entries = [
        _entry(
            "A global workspace in language models",
            "https://www.anthropic.com/research/global-workspace",
        ),
        _entry(
            "Anthropic's new J-lens reveals a silent workspace inside Claude",
            "https://venturebeat.com/technology/anthropics-new-j-lens",
        ),
        _entry("Microsoft layoffs", "https://techcrunch.com/ms"),
    ]
    groups = [
        ClusterGroup(entry_indices=[0], event="Anthropic global workspace"),
        ClusterGroup(entry_indices=[1], event="VB Anthropic J-lens"),
        ClusterGroup(entry_indices=[2], event="Microsoft layoffs"),
    ]
    refined = refine_cluster_groups(groups, entries, max_members=4)
    assert len(refined) == 2
    anthropic = next(g for g in refined if 0 in g.entry_indices)
    assert anthropic.entry_indices == [0, 1]


def test_openai_gpt_live_coverage_merges_via_news_outlets() -> None:
    decoder = _entry(
        "OpenAI releases new voice models for more natural live conversations",
        "https://the-decoder.com/chatgpt-can-now-listen-and-talk-at-the-same-time",
    )
    vb = _entry(
        "OpenAI launches GPT Live, a full-duplex voice upgrade that lets ChatGPT talk more like a person",
        "https://venturebeat.com/technology/openai-launches-gpt-live-a-full-duplex-voice-upgrade",
    )
    assert entries_same_event(decoder, vb)


def test_cluster_should_merge_with_uses_anchor_not_transitive_chain() -> None:
    entries = [
        _entry("OpenAI releases new voice models for more natural live conversations", "https://a"),
        _entry("OpenAI launches GPT Live voice upgrade", "https://b"),
        _entry("Unrelated robotics startup ChatGPT moment", "https://c"),
    ]
    anchor_cluster = StoryCluster(
        entry_indices=[0, 1],
        ai_relevant=True,
        significance=8,
        reason="openai voice",
    )
    robotics = StoryCluster(
        entry_indices=[2],
        ai_relevant=True,
        significance=7,
        reason="robotics",
    )
    assert cluster_is_coherent(anchor_cluster, entries)
    assert not cluster_should_merge_with(anchor_cluster, robotics, entries)


def test_coerce_incoherent_cluster_keeps_anchor_only() -> None:
    entries = [
        _entry("OpenAI voice models", "https://a"),
        _entry("Claude Code ported C&C to iOS", "https://b"),
    ]
    bad = StoryCluster(
        entry_indices=[0, 1],
        ai_relevant=True,
        significance=8,
        reason="bad merge",
    )
    coerced = coerce_coherent_clusters([bad], entries)
    assert len(coerced) == 1
    assert coerced[0].entry_indices == [0]
    assert cluster_is_coherent(coerced[0], entries)


def test_gpt56_benchmark_does_not_merge_anthropic_fable_story() -> None:
    gpt56_work = _entry(
        "OpenAI pairs its GPT-5.6 public rollout with ChatGPT Work, a new agent that handles entire workflows",
        "https://the-decoder.com/openai-pairs-its-gpt-5-6-public-rollout-with-chatgpt-work-a-new-agent-that-handles-entire-workflows/",
    )
    gpt56_bench = _entry(
        "GPT-5.6-Sol nearly matches Fable 5 on aggregated benchmarks at one-third the cost",
        "https://the-decoder.com/gpt-5-6-sol-nearly-matches-fable-5-on-aggregated-benchmarks-at-one-third-the-cost/",
    )
    anthropic = _entry(
        "Anthropic's fix for Fable 5's high cost is turning it into a manager that delegates to Sonnet 5",
        "https://the-decoder.com/anthropics-fix-for-fable-5s-high-cost-is-turning-it-into-a-manager-that-delegates-to-sonnet-5/",
    )
    assert entries_same_event(gpt56_work, gpt56_bench)
    assert not entries_same_event(gpt56_bench, anthropic)
    assert not entries_same_event(gpt56_work, anthropic)
    cluster = StoryCluster(
        entry_indices=[0, 1, 2],
        ai_relevant=True,
        significance=8,
        reason="gpt-5.6",
    )
    assert not cluster_is_coherent(cluster, [gpt56_work, gpt56_bench, anthropic])


def test_same_outlet_domain_does_not_false_merge_unrelated_stories() -> None:
    layoffs = _entry(
        "Microsoft lays off nearly 5000 employees across Xbox",
        "https://the-decoder.com/microsoft-layoffs-xbox",
    )
    chips = _entry(
        "Meta will begin production of its MTIA AI chips in September",
        "https://the-decoder.com/meta-mtia-chips-september",
    )
    assert not entries_same_event(layoffs, chips)


def test_gpt56_launch_angles_merge_across_outlets() -> None:
    launch = _entry(
        "OpenAI launches its new family of models with GPT-5.6",
        "https://the-decoder.com/openai-launches-its-new-family-of-models-with-gpt-5-6",
    )
    copilot = _entry(
        "OpenAI says GPT 5.6 is the preferred model for Microsoft Copilot 365 amid breakup chatter",
        "https://techcrunch.com/2026/07/10/openai-says-gpt-5-6-preferred-microsoft-copilot-365",
    )
    assert entries_same_event(launch, copilot)


def test_merge_duplicate_event_clusters_folds_selected() -> None:
    entries = [
        _entry("OpenAI launches GPT-5.6", "https://a"),
        _entry("OpenAI GPT 5.6 preferred for Copilot", "https://b"),
        _entry("Meta MTIA chips", "https://c"),
    ]
    clusters = [
        StoryCluster(entry_indices=[0], ai_relevant=True, significance=8, reason="a"),
        StoryCluster(entry_indices=[1], ai_relevant=True, significance=7, reason="b"),
        StoryCluster(entry_indices=[2], ai_relevant=True, significance=6, reason="c"),
    ]
    merged = merge_duplicate_event_clusters(clusters, entries)
    assert len(merged) == 2
    openai = next(c for c in merged if 0 in c.entry_indices or 1 in c.entry_indices)
    assert openai.entry_indices == [0, 1]
    assert_unique_event_clusters(merged, entries)


def test_full_text_preview_does_not_false_match_unrelated_openai_stories() -> None:
    apple = _entry(
        "Apple sues OpenAI over alleged trade secret theft",
        "https://techcrunch.com/apple-sues-openai",
        summary="",
    )
    apple = apple.model_copy(
        update={
            "full_text": (
                "OpenAI GPT-5.6 Sol reasoning trade secret Siri ChatGPT lawsuit Apple filed "
                "today alleging OpenAI stole proprietary integration methods."
            )
        }
    )
    gpt56 = _entry(
        "OpenAI staffer maps out which of GPT-5.6 Sol's five reasoning levels fits which task complexity",
        "https://the-decoder.com/openai-staffer-maps-out-which-of-gpt-5-6-sols-five-reasoning-levels-fits-which-task-complexity/",
    )
    gpt56 = gpt56.model_copy(
        update={
            "full_text": (
                "OpenAI staffer explains GPT-5.6 Sol reasoning levels for different task complexity."
            )
        }
    )
    assert not entries_same_event(apple, gpt56)
