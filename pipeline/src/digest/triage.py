"""Stage A: cheap triage with gpt-5-nano.

Sees only headlines + short previews (never full articles), clusters duplicate
coverage of the same story, and ranks clusters by significance to engineers.
Full-text extraction happens only for the winners.
"""

from __future__ import annotations

import logging

from openai import OpenAI

from .config import TRIAGE_MODEL
from .costs import CostTracker
from .models import FeedEntry, StoryCluster, TriageResult

logger = logging.getLogger(__name__)

# Clusters below this score are dropped in code, not just in the prompt.
MIN_SIGNIFICANCE = 4
# Real duplicate coverage is 2-4 outlets; larger clusters are topic buckets.
MAX_CLUSTER_MEMBERS = 4

# Static, byte-identical system prompt -> automatic prefix caching across runs.
TRIAGE_SYSTEM_PROMPT = """\
You are the wire editor for "The Morning Build", a daily digest for people who
build software in the AI era. You receive a numbered list of candidate articles
(headline, source, short preview).

Your tasks:
1. Cluster entries ONLY when multiple outlets report the SAME specific news
   event (same product launch, funding round, court ruling, or policy
   announcement). Different companies making different announcements are ALWAYS
   separate clusters, even on the same day or about the same broad topic (e.g.
   "AI agents" or "big tech AI"). Different announcements from the same
   company are also separate clusters. Never group articles because they share
   a theme, sector, or keyword.
2. Set ai_relevant to true when the story belongs in a builder-focused AI
   digest (see scoring tiers below). Set false for consumer gadgets,
   entertainment, sports, pure funding/valuation news with no product angle,
   and unrelated business news.
3. Score significance from 1-10. The final digest mixes product news with
   higher-level context from big players; rank accordingly:
   - 8-10 (Tier A): Shipped or previewing models, APIs, SDKs, agent tooling,
     dev integrations, open-source releases, inference/compute readers can
     provision, policy that changes model access or training data (e.g.
     crawler defaults, export clearance).
   - 5-7 (Tier B): Big-player strategy and infrastructure context: major
     vendor compute moves, platform bets, internal roadmap signals from
     Meta/Google/OpenAI/Anthropic/Nvidia, export or regulatory shifts that
     reshape the ecosystem even without a specific API to call today.
     Tier B from a big player often beats a minor Tier A launch.
   - 1-4 (Tier C): Funding rounds and unicorn valuations with no shipped
     product, executive drama, consumer hardware features and subscription
     pricing (smart glasses, phones), "reportedly exploring" with no concrete
     product or access change. Score 3 or lower; set ai_relevant false for
     consumer hardware pricing. Only score Tier C at 4+ on an extremely thin
     news day when fewer than three Tier A or B clusters exist.
   Prefer a digest that mixes Tier A and Tier B (mostly A, several B for
   context), not a business roundup of Tier C stories.
4. Give a one-line reason per cluster.

Return every cluster scoring 4 or higher; the pipeline selects the final
digest. Omit only clear noise (3 or lower). No candidate in more than one
cluster. Order by significance, highest first.
"""


def build_triage_input(entries: list[FeedEntry]) -> str:
    lines = ["Candidate articles:"]
    for i, entry in enumerate(entries):
        lines.append(f"[{i}] ({entry.source}) {entry.title}\n{entry.preview(80)}")
    return "\n\n".join(lines)


def split_oversized_clusters(raw: list[StoryCluster]) -> list[StoryCluster]:
    """Split topic-bucket clusters into singletons before ranking."""
    split: list[StoryCluster] = []
    for cluster in raw:
        if len(cluster.entry_indices) <= MAX_CLUSTER_MEMBERS:
            split.append(cluster)
            continue
        logger.warning(
            "Splitting oversized cluster (%d members, score %d)",
            len(cluster.entry_indices),
            cluster.significance,
        )
        for idx in cluster.entry_indices:
            split.append(cluster.model_copy(update={"entry_indices": [idx]}))
    return split


def select_clusters(
    raw: list[StoryCluster],
    entries: list[FeedEntry],
    max_stories: int,
) -> list[StoryCluster]:
    """Keep top AI-relevant clusters by significance, at most max_stories."""
    valid_range = range(len(entries))
    used: set[int] = set()
    clusters: list[StoryCluster] = []
    for cluster in sorted(raw, key=lambda c: c.significance, reverse=True):
        indices = [i for i in cluster.entry_indices if i in valid_range and i not in used]
        if not indices:
            continue
        headline = entries[indices[0]].title
        if not cluster.ai_relevant:
            logger.info("Triage CUT (not AI-relevant, %d): %s", cluster.significance, headline)
            continue
        if cluster.significance < MIN_SIGNIFICANCE:
            logger.info("Triage CUT (score %d): %s", cluster.significance, headline)
            continue
        if len(clusters) >= max_stories:
            logger.info("Triage CUT (over limit, %d): %s", cluster.significance, headline)
            continue
        used.update(indices)
        clusters.append(cluster.model_copy(update={"entry_indices": indices}))
        logger.info(
            "Triage KEPT (%d): %s | %s", cluster.significance, headline, cluster.reason
        )
    return clusters


def triage(
    client: OpenAI,
    entries: list[FeedEntry],
    max_stories: int,
    tracker: CostTracker,
) -> list[StoryCluster]:
    """Return the top clusters (at most max_stories), validated against the input."""
    tracker.check_budget()
    response = client.responses.parse(
        model=TRIAGE_MODEL,
        reasoning={"effort": "minimal"},
        max_output_tokens=6000,
        input=[
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": build_triage_input(entries)},
        ],
        text_format=TriageResult,
    )
    tracker.record(TRIAGE_MODEL, response.usage)

    result = response.output_parsed
    if result is None:
        raise RuntimeError("Triage returned no parsed output")

    clusters = select_clusters(
        split_oversized_clusters(result.clusters), entries, max_stories
    )
    logger.info("Triage selected %d/%d clusters", len(clusters), len(result.clusters))
    return clusters
