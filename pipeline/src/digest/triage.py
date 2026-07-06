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
from .quality import ABS_MIN_STORIES

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
   a theme, sector, or keyword. HARD LIMIT: a cluster may contain at most
   four entry indices. If articles are not the same event, use singleton
   clusters (one index each).
2. Classify each cluster into Tier A, B, or C (below), then set ai_relevant:
   true ONLY for Tier A or Tier B clusters; false for Tier C and anything
   outside this digest (consumer gadgets, entertainment, sports, unrelated
   business news).
3. Score significance from 1-10 within the tier. The daily digest is for
   people who build software with AI: mostly product and platform news, plus
   higher-level context from major vendors when the story is big. Rank
   accordingly:
   - 8-10 (Tier A): What builders can use or deploy soon. Examples: model or
     API/SDK launches and previews; new model tiers or modes in Codex,
     Copilot, Claude Code, Cursor, or major coding APIs (including limited
     previews and "coming to Codex/API" announcements); agent tooling and
     dev integrations; major open-source ML releases; inference or compute
     readers can provision; chips and training/inference stack changes;
     policy that directly changes model access, APIs, or training data
     (crawler defaults, export clearance, licensing). Headlines naming a
     model version plus Codex, API, SDK, or agent tooling are Tier A even
     when the RSS preview is thin or the headline says "will be".
   - 5-7 (Tier B): Big-player ecosystem context worth knowing even without a
     new API to call today. Examples: major vendor compute or hosting
     strategy (Meta, Google, OpenAI, Anthropic, Nvidia, Microsoft, Amazon);
     platform bets and internal roadmap signals from those vendors; export or
     regulatory shifts that reshape what teams can ship globally. A Tier B
     story from a major vendor outranks a minor Tier A launch from a small
     player, but on a normal news day most selected clusters should still be
     Tier A.
   - 1-4 (Tier C): Out of scope for this digest. Examples: funding rounds and
     unicorn valuations with no shipped product; startup accelerators and
     incubator cohort announcements without a shipped product or API; executive
     drama; consumer hardware features and subscription pricing (smart glasses,
     phones); "reportedly exploring" with no concrete product or access change. Always score 3 or lower and set ai_relevant false. Never
     include consumer hardware pricing, even on a thin news day.
   When ranking clusters for the digest: prefer a mix of Tier A and Tier B
   (mostly A, two or three B for context). Model, API, and dev-tool releases
   from major labs outrank accelerators, legacy platform sunsets, and generic
   policy commentary unless the policy directly changes what builders can
   ship. Do not fill slots with Tier C stories when Tier A or B options exist.
4. Give a one-line reason per cluster.

Return every cluster scoring 4 or higher; the pipeline selects the final
digest. Omit only clear noise (3 or lower). No candidate in more than one
cluster. Order by significance, highest first.
"""

# Used when the model returns a theme bucket (>4 members). Bucket-level
# ai_relevant/significance is unreliable, so each article is re-scored alone.
RECLASSIFY_SYSTEM_PROMPT = """\
You are the wire editor for "The Morning Build", a daily digest for people who
build software in the AI era.

Each article must be its own cluster: exactly one entry index per cluster.
Never group multiple articles.

Classify each cluster into Tier A, B, or C, then set ai_relevant true ONLY
for Tier A or Tier B; false for Tier C and out-of-scope stories (consumer
gadgets, entertainment, sports, unrelated business news).

Score significance 1-10:
- 8-10 (Tier A): model/API launches; new tiers or modes in Codex, Copilot,
  Claude Code, Cursor, or major coding APIs (including "coming to Codex/API");
  agent tooling; open-source ML; chips; inference/compute readers can use;
  policy that changes model access. Thin or headline-only previews do not
  downgrade these — score from the headline.
- 5-7 (Tier B): major vendor ecosystem moves (OpenAI, Anthropic, Google,
  Microsoft, Meta, Nvidia, Amazon), export/regulatory shifts.
- 1-4 (Tier C): funding with no product; accelerators without shipped APIs;
  executive drama; consumer hardware; vague "reportedly exploring". Score 3
  or lower and ai_relevant false.

Return one cluster per article that scores 4 or higher. Omit only clear noise.
"""


def build_triage_input(entries: list[FeedEntry]) -> str:
    lines = ["Candidate articles:"]
    for i, entry in enumerate(entries):
        lines.append(
            f"[{i}] ({entry.source}, {entry.topic}) {entry.title}\n{entry.preview(80)}"
        )
    return "\n\n".join(lines)


def build_reclassify_input(entries: list[FeedEntry], indices: list[int]) -> str:
    lines = [
        "Re-classify each article individually (one cluster per article):",
    ]
    for sub_i, entry_i in enumerate(indices):
        entry = entries[entry_i]
        lines.append(
            f"[{sub_i}] ({entry.source}, {entry.topic}) {entry.title}\n{entry.preview(80)}"
        )
    return "\n\n".join(lines)


def remap_cluster_indices(
    clusters: list[StoryCluster], index_map: dict[int, int]
) -> list[StoryCluster]:
    """Map local reclassify indices back onto the full candidate list."""
    remapped: list[StoryCluster] = []
    for cluster in clusters:
        indices = [index_map[i] for i in cluster.entry_indices if i in index_map]
        if indices:
            remapped.append(cluster.model_copy(update={"entry_indices": indices}))
    return remapped


def split_oversized_clusters(
    raw: list[StoryCluster],
) -> tuple[list[StoryCluster], frozenset[int]]:
    """Split topic-bucket clusters; return indices that need reclassification."""
    split: list[StoryCluster] = []
    repriced: set[int] = set()
    for cluster in raw:
        if len(cluster.entry_indices) <= MAX_CLUSTER_MEMBERS:
            split.append(cluster)
            continue
        logger.warning(
            "Oversized cluster (%d members, score %d, ai_relevant=%s); "
            "will reclassify each article individually",
            len(cluster.entry_indices),
            cluster.significance,
            cluster.ai_relevant,
        )
        repriced.update(cluster.entry_indices)
    return split, frozenset(repriced)


def replace_repriced_clusters(
    clusters: list[StoryCluster],
    repriced: frozenset[int],
    replacements: list[StoryCluster],
) -> list[StoryCluster]:
    """Drop bucket-derived singletons and substitute per-article scores."""
    kept = [
        c
        for c in clusters
        if not (len(c.entry_indices) == 1 and c.entry_indices[0] in repriced)
    ]
    return kept + replacements


def reclassify_entries(
    client: OpenAI,
    entries: list[FeedEntry],
    indices: list[int],
    tracker: CostTracker,
) -> list[StoryCluster]:
    """Score articles individually after a failed theme-bucket cluster."""
    if not indices:
        return []
    tracker.check_budget()
    index_map = {sub_i: orig_i for sub_i, orig_i in enumerate(indices)}
    response = client.responses.parse(
        model=TRIAGE_MODEL,
        reasoning={"effort": "minimal"},
        max_output_tokens=6000,
        input=[
            {"role": "system", "content": RECLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": build_reclassify_input(entries, indices)},
        ],
        text_format=TriageResult,
    )
    tracker.record(TRIAGE_MODEL, response.usage)
    result = response.output_parsed
    if result is None:
        raise RuntimeError("Reclassify triage returned no parsed output")
    return remap_cluster_indices(result.clusters, index_map)


def run_triage_selection(
    client: OpenAI,
    entries: list[FeedEntry],
    raw_clusters: list[StoryCluster],
    max_stories: int,
    tracker: CostTracker,
) -> list[StoryCluster]:
    """Split, reclassify bucket mistakes, select, then fall back if still empty."""
    split, repriced = split_oversized_clusters(raw_clusters)
    if repriced:
        replacements = reclassify_entries(client, entries, sorted(repriced), tracker)
        split = replace_repriced_clusters(split, repriced, replacements)

    clusters = select_clusters(split, entries, max_stories)
    if not clusters and len(entries) >= ABS_MIN_STORIES:
        logger.warning(
            "Triage selected 0 clusters with %d candidates; "
            "individual reclassify fallback",
            len(entries),
        )
        individuals = reclassify_entries(
            client, entries, list(range(len(entries))), tracker
        )
        clusters = select_clusters(individuals, entries, max_stories)
    return clusters


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

    clusters = run_triage_selection(client, entries, result.clusters, max_stories, tracker)
    logger.info("Triage selected %d/%d clusters", len(clusters), len(result.clusters))
    return clusters
