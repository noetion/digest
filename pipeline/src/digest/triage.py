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

# Static, byte-identical system prompt -> automatic prefix caching across runs.
# Never interpolate anything dynamic into this string.
TRIAGE_SYSTEM_PROMPT = """\
You are the wire editor for a daily tech digest read by software engineers and
AI practitioners. You receive a numbered list of candidate articles (headline,
source, short preview).

Your tasks:
1. Cluster entries that cover the SAME underlying story (e.g. the same launch,
   paper, funding round, or incident reported by multiple outlets) into one
   cluster. Entries about different stories must never share a cluster.
2. Score each cluster's significance to engineers/AI practitioners from 1-10.
   Prioritize: model/tooling releases, hard technical details, infrastructure,
   chips, developer-facing products, consequential industry/policy shifts.
   Deprioritize: rumor, celebrity, consumer gadget refreshes, opinion pieces.
3. Give a one-line reason per cluster.

Return every candidate in at most one cluster. Order clusters by significance,
highest first.
"""


def build_triage_input(entries: list[FeedEntry]) -> str:
    lines = ["Candidate articles:"]
    for i, entry in enumerate(entries):
        lines.append(f"[{i}] ({entry.source}) {entry.title}\n{entry.preview(80)}")
    return "\n\n".join(lines)


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
        max_output_tokens=2000,
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

    valid_range = range(len(entries))
    used: set[int] = set()
    clusters: list[StoryCluster] = []
    for cluster in sorted(result.clusters, key=lambda c: c.significance, reverse=True):
        indices = [i for i in cluster.entry_indices if i in valid_range and i not in used]
        if not indices:
            continue
        used.update(indices)
        clusters.append(cluster.model_copy(update={"entry_indices": indices}))
        if len(clusters) >= max_stories:
            break

    logger.info("Triage selected %d/%d clusters", len(clusters), len(result.clusters))
    return clusters
