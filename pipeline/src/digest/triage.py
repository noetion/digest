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

# Clusters below this score are dropped in code, not just in the prompt, so a
# thin news day produces a shorter digest instead of padded filler.
MIN_SIGNIFICANCE = 4

# Static, byte-identical system prompt -> automatic prefix caching across runs.
# Never interpolate anything dynamic into this string.
TRIAGE_SYSTEM_PROMPT = """\
You are the wire editor for "The Morning Build", a daily digest for people who
build software in the AI era: engineers, AI practitioners, and technical
founders. You receive a numbered list of candidate articles (headline, source,
short preview).

Your tasks:
1. Cluster entries that cover the SAME underlying story (e.g. the same launch,
   paper, funding round, or incident reported by multiple outlets) into one
   cluster. Entries about different stories must never share a cluster.
2. Set ai_relevant to true if the story touches the AI ecosystem: models,
   training or inference tooling, chips and compute, infrastructure and power,
   developer-facing AI products, AI policy and regulation, or how teams build
   and ship software in the AI era. A general tech story with a meaningful AI
   angle counts as true. Set it false only when the story has no real AI
   connection (gadget refreshes, entertainment, unrelated business news).
3. Score each cluster's significance from 1-10 using one question: would
   someone who builds software care about this? A 8-10 story changes what
   they build with or how (major model/tooling releases, big capability or
   pricing shifts, consequential policy). A 4-7 story informs decisions or is
   worth a builder's awareness (infrastructure moves, funding with technical
   substance, notable research, significant industry developments). A 1-3
   story is background noise: rumor, celebrity, consumer gadget refreshes,
   opinion pieces, incremental corporate news.
4. Give a one-line reason per cluster.

Return EVERY cluster with significance 4 or higher; the pipeline picks the
final digest, so do not pre-select or trim the list yourself. Omit only clear
noise (significance 3 or lower). No candidate may appear in more than one
cluster. Order clusters by significance, highest first.
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
    """Validate and filter the model's clusters: drop invalid/duplicate indices
    and anything under the significance floor, then keep the top max_stories.

    AI-relevant clusters take priority regardless of score; non-AI tech
    stories are eligible but only fill slots left over after every AI story.
    Every keep/cut decision is logged so the GitHub Actions log doubles as an
    audit trail."""
    valid_range = range(len(entries))
    used: set[int] = set()
    clusters: list[StoryCluster] = []
    ordered = sorted(raw, key=lambda c: (not c.ai_relevant, -c.significance))
    for cluster in ordered:
        indices = [i for i in cluster.entry_indices if i in valid_range and i not in used]
        if not indices:
            continue
        headline = entries[indices[0]].title
        if cluster.significance < MIN_SIGNIFICANCE:
            logger.info("Triage CUT (score %d): %s", cluster.significance, headline)
            continue
        if len(clusters) >= max_stories:
            logger.info("Triage CUT (over limit, %d): %s", cluster.significance, headline)
            continue
        used.update(indices)
        clusters.append(cluster.model_copy(update={"entry_indices": indices}))
        logger.info(
            "Triage KEPT (%d%s): %s | %s",
            cluster.significance,
            "" if cluster.ai_relevant else ", non-AI",
            headline,
            cluster.reason,
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
        # Generous cap: a truncated structured output fails to parse and kills
        # the run. nano output is $0.40/M, so the headroom costs fractions of
        # a cent at worst.
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
