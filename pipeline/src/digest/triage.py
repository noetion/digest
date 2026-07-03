"""Stage A: cheap triage with gpt-5-nano.

Sees only headlines + short previews (never full articles), clusters duplicate
coverage of the same story, and ranks clusters by significance to engineers.
Full-text extraction happens only for the winners.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from openai import OpenAI

from .config import TRIAGE_MODEL
from .costs import CostTracker
from .models import FeedEntry, StoryCluster, TriageResult

logger = logging.getLogger(__name__)

# Clusters below this score are dropped in code, not just in the prompt, so a
# thin news day produces a shorter digest instead of padded filler.
MIN_SIGNIFICANCE = 4
# No more than this many clusters whose primary outlet is the same domain.
MAX_CLUSTERS_PER_DOMAIN = 2
MERGE_KEYWORD_OVERLAP = 0.5

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have",
        "he", "her", "his", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the",
        "their", "they", "this", "to", "was", "were", "will", "with", "after", "before",
        "over", "under", "about", "when", "where", "while", "who", "why", "how", "not", "out",
        "up", "all", "any", "can", "may", "new", "now", "one", "two", "says", "said", "report",
        "reports", "reported", "than", "more", "most", "other", "some", "such", "them", "these",
        "those", "very", "what", "your", "our",
    }
)

# Static, byte-identical system prompt -> automatic prefix caching across runs.
# Never interpolate anything dynamic into this string.
TRIAGE_SYSTEM_PROMPT = """\
You are the wire editor for "The Morning Build", a daily digest for people who
build software in the AI era: engineers, AI practitioners, and technical
founders. You receive a numbered list of candidate articles (headline, source,
short preview).

Your tasks:
1. Cluster entries that cover the SAME underlying story into one cluster.
   Merge aggressively when multiple outlets report the same news: the same
   product launch, funding round, policy move, or corporate initiative
   (e.g. Meta building a cloud business to sell spare AI compute reported by
   TechCrunch and The Decoder must be ONE cluster, not two). Separate
   clusters only when the news event is genuinely different: a product launch
   is not the same story as executive commentary or a quarterly earnings
   beat, even if the same company is involved.
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


def _cluster_keywords(entries: list[FeedEntry], indices: list[int]) -> set[str]:
    words: set[str] = set()
    for i in indices:
        for token in re.findall(r"[a-z0-9]{3,}", entries[i].title.lower()):
            if token not in _STOPWORDS:
                words.add(token)
    return words


def _keyword_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    shared = len(a & b)
    # Jaccard misses same-story headlines with different framing; containment
    # catches "Meta sells spare compute" vs "Meta follows SpaceX to sell compute".
    jaccard = shared / len(a | b)
    containment = shared / min(len(a), len(b))
    return max(jaccard, containment)


def _cluster_domain(entries: list[FeedEntry], indices: list[int]) -> str:
    """Best guess at the primary outlet for a cluster (longest preview wins)."""
    best = max(indices, key=lambda i: len(entries[i].preview(80)))
    return urlsplit(entries[best].url).netloc.removeprefix("www.")


def merge_duplicate_clusters(
    raw: list[StoryCluster],
    entries: list[FeedEntry],
    overlap_threshold: float = MERGE_KEYWORD_OVERLAP,
) -> list[StoryCluster]:
    """Merge clusters the model split that clearly cover the same story."""
    merged: list[StoryCluster] = []
    for cluster in raw:
        indices = [i for i in cluster.entry_indices if i < len(entries)]
        if not indices:
            continue
        keywords = _cluster_keywords(entries, indices)
        headline = entries[indices[0]].title

        combined = False
        for pos, existing in enumerate(merged):
            existing_indices = existing.entry_indices
            overlap = _keyword_overlap(keywords, _cluster_keywords(entries, existing_indices))
            if overlap < overlap_threshold:
                continue
            new_indices = list(dict.fromkeys(existing_indices + indices))
            keep_existing_reason = existing.significance >= cluster.significance
            merged[pos] = StoryCluster(
                entry_indices=new_indices,
                ai_relevant=existing.ai_relevant or cluster.ai_relevant,
                significance=max(existing.significance, cluster.significance),
                reason=existing.reason if keep_existing_reason else cluster.reason,
            )
            logger.info(
                "Triage MERGE (%.0f%% overlap): %s",
                overlap * 100,
                headline,
            )
            combined = True
            break
        if not combined:
            merged.append(cluster.model_copy(update={"entry_indices": indices}))
    return merged


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
    domain_counts: dict[str, int] = {}
    ordered = sorted(raw, key=lambda c: (not c.ai_relevant, -c.significance))
    for cluster in ordered:
        indices = [i for i in cluster.entry_indices if i in valid_range and i not in used]
        if not indices:
            continue
        headline = entries[indices[0]].title
        if cluster.significance < MIN_SIGNIFICANCE:
            logger.info("Triage CUT (score %d): %s", cluster.significance, headline)
            continue
        domain = _cluster_domain(entries, indices)
        if domain_counts.get(domain, 0) >= MAX_CLUSTERS_PER_DOMAIN:
            logger.info("Triage CUT (domain cap %s): %s", domain, headline)
            continue
        if len(clusters) >= max_stories:
            logger.info("Triage CUT (over limit, %d): %s", cluster.significance, headline)
            continue
        used.update(indices)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
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

    merged = merge_duplicate_clusters(result.clusters, entries)
    clusters = select_clusters(merged, entries, max_stories)
    logger.info(
        "Triage selected %d/%d clusters (%d after merge)",
        len(clusters),
        len(result.clusters),
        len(merged),
    )
    return clusters
