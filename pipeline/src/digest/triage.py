"""Stage A: cheap triage with gpt-5-nano.

Architecture:
  1. Start every candidate as its own group (no LLM grouping).
  2. Deterministic duplicate merge (same event, multiple outlets).
  3. LLM scores every article individually.
  4. Attach scores to groups; split any incoherent multi-member cluster.
  5. Tier-aware selection with rank adjustments (editorial.py).

Full-text extraction runs only on the winners.
"""

from __future__ import annotations

import logging

from openai import OpenAI

from .config import TRIAGE_MODEL
from .costs import CostTracker
from .editorial import SELECTION_RESERVE_DEPTH, rank_selection_candidates
from .event_match import (
    MAX_EVENT_CLUSTER_MEMBERS,
    refine_cluster_groups,
    singleton_groups,
    split_incoherent_clusters,
)
from .models import (
    ClusterGroup,
    FeedEntry,
    ScoreResult,
    StoryCluster,
)

logger = logging.getLogger(__name__)

MAX_CLUSTER_MEMBERS = MAX_EVENT_CLUSTER_MEMBERS

SCORE_SYSTEM_PROMPT = """\
You are the wire editor for "The Morning Build", a daily digest for people who
build software in the AI era.

Each article must be its own cluster: exactly one entry index per cluster.
Never group multiple articles.

Use the FULL 1-10 scale with real spread. Most days have zero or one 9-10 story,
a handful of 6-7 stories, and many 3-5 cuts. Do NOT default everything to 7.

Classify each cluster into Tier A, B, or C, then set ai_relevant true ONLY
for Tier A or Tier B; false for Tier C and out-of-scope stories.

Score significance 1-10:
- 8-10 (Tier A): model/API launches; new tiers or modes in Codex, Copilot,
  Claude Code, Cursor, or major coding APIs; agent tooling; open-source ML;
  datacenter chips and cloud GPU/inference readers deploy against; policy that
  changes model access. Thin previews do not downgrade these — score from the headline.
- 5-7 (Tier B): major vendor ecosystem moves, export/regulatory shifts that
  reshape what teams can ship, named layoffs or reorgs at platform-scale vendors
  (Microsoft, Google, Meta, Amazon, Apple, Nvidia, and peers — score 6-8 when
  thousands of roles or a major division is affected; not industry roundups),
  and in-depth production ML / agent orchestration engineering posts (score 6-7).
- 1-4 (Tier C): funding with no product; accelerators; retail dev kits and
  consumer/prosumer hardware ($4k AI boxes, Ryzen NUC-style kits, gaming GPUs);
  iOS/macOS beta UX (Siri voice sliders, widget tweaks, pace/expressivity
  settings) — NOT SDK/API releases; vague "reportedly exploring"; travel/retail
  case studies with no engineering lessons. Score 3 or lower, ai_relevant false.

When stories compete in Tier B, favor concrete big-vendor workforce moves,
production ML / agent orchestration engineering posts, and product-policy
changes over generic regulator commentary. Model/API/dev-tool releases
outrank accelerators and vague policy unless the policy directly changes
deployment.

Return one cluster per article that scores 4 or higher. Omit only clear noise.
"""


def build_score_input(entries: list[FeedEntry], indices: list[int]) -> str:
    lines = ["Score each article individually (one cluster per article):"]
    for sub_i, entry_i in enumerate(indices):
        entry = entries[entry_i]
        lines.append(
            f"[{sub_i}] ({entry.source}, {entry.topic}) {entry.title}\n{entry.preview(80)}"
        )
    return "\n\n".join(lines)


def normalize_cluster_groups(
    groups: list[ClusterGroup], n_entries: int
) -> list[list[int]]:
    """Ensure every candidate index appears in exactly one group."""
    used: set[int] = set()
    normalized: list[list[int]] = []
    valid = range(n_entries)

    for group in groups:
        indices = [i for i in group.entry_indices if i in valid and i not in used]
        if indices:
            used.update(indices)
            normalized.append(indices)

    for i in valid:
        if i not in used:
            normalized.append([i])

    return normalized


def merge_cluster_scores(
    groups: list[ClusterGroup],
    scored: dict[int, StoryCluster],
    n_entries: int,
) -> list[StoryCluster]:
    """Attach pass-2 scores to duplicate groups; dissolve invalid buckets."""
    merged: list[StoryCluster] = []
    for indices in normalize_cluster_groups(groups, n_entries):
        if len(indices) > MAX_CLUSTER_MEMBERS:
            logger.warning(
                "Dissolving oversized cluster (%d members); scoring individually",
                len(indices),
            )
            for i in sorted(indices):
                if i in scored:
                    merged.append(scored[i])
            continue

        scored_members = [i for i in indices if i in scored]
        if not scored_members:
            continue
        best_i = max(scored_members, key=lambda i: scored[i].significance)
        best = scored[best_i]
        merged.append(
            StoryCluster(
                entry_indices=indices,
                ai_relevant=best.ai_relevant,
                significance=best.significance,
                reason=best.reason,
            )
        )
    return merged


def remap_score_indices(
    clusters: list[StoryCluster], index_map: dict[int, int]
) -> dict[int, StoryCluster]:
    """Map local score-pass indices back onto the full candidate list."""
    scored: dict[int, StoryCluster] = {}
    for cluster in clusters:
        indices = [index_map[i] for i in cluster.entry_indices if i in index_map]
        if len(indices) == 1:
            scored[indices[0]] = cluster.model_copy(update={"entry_indices": indices})
    return scored


def score_entries(
    client: OpenAI,
    entries: list[FeedEntry],
    indices: list[int],
    tracker: CostTracker,
) -> dict[int, StoryCluster]:
    """Score every article individually."""
    if not indices:
        return {}
    tracker.check_budget()
    index_map = {sub_i: orig_i for sub_i, orig_i in enumerate(indices)}
    response = client.responses.parse(
        model=TRIAGE_MODEL,
        reasoning={"effort": "low"},
        max_output_tokens=6000,
        input=[
            {"role": "system", "content": SCORE_SYSTEM_PROMPT},
            {"role": "user", "content": build_score_input(entries, indices)},
        ],
        text_format=ScoreResult,
    )
    tracker.record(TRIAGE_MODEL, response.usage)
    result = response.output_parsed
    if result is None:
        raise RuntimeError("Score pass returned no parsed output")
    scored = remap_score_indices(result.clusters, index_map)
    logger.info("Score pass: %d/%d articles scored 4+", len(scored), len(indices))
    return scored


def triage(
    client: OpenAI,
    entries: list[FeedEntry],
    max_stories: int,
    tracker: CostTracker,
) -> list[StoryCluster]:
    """Return the top clusters (at most max_stories), validated against the input."""
    groups = refine_cluster_groups(
        singleton_groups(entries),
        entries,
        max_members=MAX_CLUSTER_MEMBERS,
    )
    logger.info(
        "Duplicate merge: %d candidates -> %d event clusters",
        len(entries),
        len(groups),
    )
    scored = score_entries(client, entries, list(range(len(entries))), tracker)
    merged = split_incoherent_clusters(
        merge_cluster_scores(groups, scored, len(entries)),
        entries,
    )
    clusters = rank_selection_candidates(
        merged,
        entries,
        max_candidates=max(max_stories, SELECTION_RESERVE_DEPTH),
    )
    logger.info(
        "Triage ranked %d candidates (target %d, reserve %d)",
        len(clusters),
        max_stories,
        SELECTION_RESERVE_DEPTH,
    )
    return clusters
