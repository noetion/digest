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

# Static, byte-identical system prompt -> automatic prefix caching across runs.
TRIAGE_SYSTEM_PROMPT = """\
You are the wire editor for "The Morning Build", a daily digest for people who
build software in the AI era. You receive a numbered list of candidate articles
(headline, source, short preview).

Your tasks:
1. Cluster entries that cover the SAME underlying news event into one cluster.
   Multiple outlets reporting the same launch, funding round, or policy move
   belong together. Separate clusters when the news event is different, even
   if the same company is involved.
2. Set ai_relevant to true when the story meaningfully affects people who build
   with AI: models, training or inference tooling, chips and compute for AI
   workloads, AI infrastructure and datacenters, developer-facing AI products
   and APIs, AI-specific policy, and closely adjacent news (semiconductor or
   cloud moves clearly driven by AI demand, major ML open-source releases,
   platform changes engineers use to ship AI features). General consumer
   gadgets, entertainment, sports, and unrelated business news gets
   ai_relevant false.
3. Score each cluster's significance from 1-10: would someone who builds
   software in the AI era care about this? 8-10 changes what they build with
   or how. 4-7 is worth awareness. 1-3 is noise.
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

    clusters = select_clusters(result.clusters, entries, max_stories)
    logger.info("Triage selected %d/%d clusters", len(clusters), len(result.clusters))
    return clusters
