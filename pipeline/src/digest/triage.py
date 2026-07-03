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
2. Classify each cluster into Tier A, B, or C (below), then set ai_relevant:
   true ONLY for Tier A or Tier B clusters; false for Tier C and anything
   outside this digest (consumer gadgets, entertainment, sports, unrelated
   business news).
3. Score significance from 1-10 within the tier. The daily digest is for
   people who build software with AI: mostly product and platform news, plus
   higher-level context from major vendors when the story is big. Rank
   accordingly:
   - 8-10 (Tier A): What builders can use or deploy soon. Examples: model or
     API/SDK launches and previews; agent tooling and dev integrations;
     major open-source ML releases; inference or compute readers can
     provision; chips and training/inference stack changes; policy that
     directly changes model access, APIs, or training data (crawler defaults,
     export clearance, licensing).
   - 5-7 (Tier B): Big-player ecosystem context worth knowing even without a
     new API to call today. Examples: major vendor compute or hosting
     strategy (Meta, Google, OpenAI, Anthropic, Nvidia, Microsoft, Amazon);
     platform bets and internal roadmap signals from those vendors; export or
     regulatory shifts that reshape what teams can ship globally. A Tier B
     story from a major vendor outranks a minor Tier A launch from a small
     player, but on a normal news day most selected clusters should still be
     Tier A.
   - 1-4 (Tier C): Out of scope for this digest. Examples: funding rounds and
     unicorn valuations with no shipped product; executive drama; consumer
     hardware features and subscription pricing (smart glasses, phones);
     "reportedly exploring" with no concrete product or access change. Always
     score 3 or lower and set ai_relevant false. Never include consumer
     hardware pricing, even on a thin news day.
   When ranking clusters for the digest: prefer a mix of Tier A and Tier B
   (mostly A, two or three B for context). Do not fill slots with Tier C
   stories when Tier A or B options exist.
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
