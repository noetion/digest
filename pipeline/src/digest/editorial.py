"""Editorial policy enforced in code — not left to LLM luck alone.

The LLM proposes scores; Python applies Morning Build policy: theme-family caps,
consumer-noise exclusion, and headline-based rank adjustments so similar raw
scores still differentiate (e.g. Microsoft layoffs vs iOS Siri beta).
"""

from __future__ import annotations

import logging
import re

from .models import FeedEntry, StoryCluster

logger = logging.getLogger(__name__)

MIN_SIGNIFICANCE = 4
TIER_A_MIN = 8
TIER_B_MIN = 5
MAX_TIER_A_SLOTS = 2
# Ranked depth for extract backfill when winners fail (same editorial gates apply).
SELECTION_RESERVE_DEPTH = 15

FAMILY_LIMITS: dict[str, int] = {
    "workforce": 1,
    "regulatory_commentary": 1,
}

# Light balance: avoid three-plus stories centered on the same regional vendor cluster.
GEO_LIMITS: dict[str, int] = {
    "asia_vendor": 2,
}

# Light diversity: one outlet should not dominate the whole digest.
MAX_STORIES_PER_SOURCE = 2

# When nano under-scores a named big-vendor workforce move, Python enforces Tier B floor.
MAJOR_WORKFORCE_SCORE_FLOOR = 6

TOPIC_RANK: dict[str, int] = {
    "dev-tools": 0,
    "ai": 1,
    "chips": 2,
    "big-tech": 3,
    "startups": 4,
    "policy": 5,
}

_WORKFORCE = re.compile(
    r"\b(?:layoffs?|lay\s+off|lays\s+off|laid\s+off|job\s+cuts?|workforce\s+cuts?|"
    r"cuts?\s+\d[\d,.\s]*\s*(?:roles|jobs|employees|staff|workers))\b",
    re.IGNORECASE,
)
_WORKFORCE_ROUNDUP = re.compile(
    r"\b(?:running\s+list|major\s+tech\s+layoffs|list\s+of\s+.*layoffs?|"
    r"every\s+major\s+tech\s+layoff)\b",
    re.IGNORECASE,
)
# Platform-scale vendors: workforce moves here are digest-worthy when specific.
_MAJOR_PLATFORM = re.compile(
    r"\b(?:microsoft|google|alphabet|meta|facebook|amazon|apple|nvidia|intel|"
    r"salesforce|oracle|ibm|adobe|netflix|uber|spotify|tesla|"
    r"openai|anthropic|palantir|snap(?:chat)?|block|square|paypal|"
    r"shopify|stripe|cloudflare|vercel|datadog|snowflake|servicenow|"
    r"linkedin|airbnb|doordash|byte(?:dance|dance)?)\b",
    re.IGNORECASE,
)

_REGULATORY_ACTOR = re.compile(
    r"\b(?:regulator(?:s|y)?|fca|sec\b|ftc|ofcom|eu\s+commission)\b",
    re.IGNORECASE,
)
_REGULATORY_META = re.compile(
    r"\b(?:arms\s+race|keeping\s+up|need\s+(?:more|new)\s+powers?|"
    r"review\s+whether|regulatory\s+perimeter|struggling\s+to\s+keep\s+up)\b",
    re.IGNORECASE,
)
_PRODUCT_POLICY = re.compile(
    r"\b(?:opt[\s-]?out|opted\s+out|ban(?:s|ned|ning)?|blocked|sunset|"
    r"export\s+(?:control|ban|restrict)|will\s+stop\s+accepting|"
    r"default(?:s|-on)?\s+(?:on|setting))\b",
    re.IGNORECASE,
)

# OS beta UX — not SDK/API releases builders ship against.
_CONSUMER_BETA = re.compile(
    r"\b(?:ios\s+\d+|ipados|developer\s+beta|public\s+beta|beta\s+\d|"
    r"siri|pace\s+and\s+expressivity|expressivity|voice\s+slider)\b",
    re.IGNORECASE,
)
_OPEN_MODEL = re.compile(
    r"\b(?:open[\s-]?source|apache\s+2\.0|open[\s-]?weight|"
    r"hy\d+|gpt[\d.\-]+|glm[\d.\-]+)\b",
    re.IGNORECASE,
)
_CODING_AGENT = re.compile(
    r"\b(?:codex|claude\s+code|cursor|zcode|coding\s+agent|copilot)\b",
    re.IGNORECASE,
)
# Retail/prosumer hardware — not datacenter GPUs or APIs teams deploy against.
_DATACENTER_HARDWARE = re.compile(
    r"\b(?:datacenter|data\s+center|h100|h200|b200|blackwell|cuda|"
    r"inference\s+api|cloud\s+gpu|training\s+cluster)\b",
    re.IGNORECASE,
)
_CONSUMER_HARDWARE = re.compile(
    r"\b(?:dev\s+kit|developer\s+kit|\$\d+k\b|\$\d{1,2},?\d{3}\b|"
    r"ryzen\s+ai|intel\s+nuc|mini\s+pc|gaming\s+gpu|graphics\s+card|"
    r"raspberry\s+pi)\b",
    re.IGNORECASE,
)
_PRODUCTION_ML = re.compile(
    r"\b(?:production\s+ml|agentic\s+release|release\s+gate|tollgate|"
    r"billions\s+of\s+(?:ai\s+)?predictions|engineering\s+principles|"
    r"sdlc|ml\s+platform|model\s+deployment\s+at\s+scale|orchestration)\b",
    re.IGNORECASE,
)
_ASIA_VENDOR = re.compile(
    r"\b(?:tencent|zhipu|baidu|alibaba|bytedance|huawei|deepseek|kuaishou|"
    r"sensetime|iflytek|meituan|hunyuan)\b",
    re.IGNORECASE,
)
_META_ANALYSIS = re.compile(
    r"\b(?:median tenure|capabilities index|epoch capabilities|"
    r"held the top spot|leadership cycles|barely survive|"
    r"number one since|top.?model tenure)\b",
    re.IGNORECASE,
)
# One-off agent demos (game ports, stunt repos): not production ships.
_AGENT_DEMO_STUNT = re.compile(
    r"\b(?:command\s+(?:&|and)\s+conquer|"
    r"port(?:ed|ing)?\s+(?:the\s+)?(?:2003\s+)?(?:pc\s+)?game|"
    r"port(?:ed|ing)?\s+to\s+native\s+(?:ios|android|ipad)|"
    r"game\s+port|zero hour|"
    r"in a few hours|overnight\s+port)\b",
    re.IGNORECASE,
)


def is_consumer_beta_noise(headline: str) -> bool:
    return bool(_CONSUMER_BETA.search(headline))


def is_consumer_hardware_noise(headline: str) -> bool:
    if _DATACENTER_HARDWARE.search(headline):
        return False
    return bool(_CONSUMER_HARDWARE.search(headline))


def editorial_family(headline: str) -> str | None:
    """Loose theme bucket for slot caps. None means no family cap applies."""
    text = headline.lower()

    if _WORKFORCE.search(headline) or _WORKFORCE_ROUNDUP.search(headline):
        return "workforce"

    if _PRODUCT_POLICY.search(headline):
        return None

    if _REGULATORY_META.search(headline) and (
        _REGULATORY_ACTOR.search(headline)
        or "financial services" in text
        or "financial" in text and "regulat" in text
    ):
        return "regulatory_commentary"

    return None


def editorial_geo_bucket(headline: str) -> str | None:
    """Loose regional vendor bucket for light geographic balance."""
    if _ASIA_VENDOR.search(headline):
        return "asia_vendor"
    return None


def is_agent_demo_stunt(headline: str) -> bool:
    return bool(_AGENT_DEMO_STUNT.search(headline))


def is_specific_major_workforce_event(headline: str) -> bool:
    """Named big-vendor layoff/reorg — not industry roundups or listicles."""
    if _WORKFORCE_ROUNDUP.search(headline):
        return False
    if not _WORKFORCE.search(headline):
        return False
    return bool(_MAJOR_PLATFORM.search(headline))


def editorial_raw_significance(cluster: StoryCluster, entries: list[FeedEntry]) -> int:
    """LLM score with Python floors for stories nano often under-ranks."""
    headline = _headline(cluster, entries)
    raw = cluster.significance
    if is_specific_major_workforce_event(headline):
        return max(raw, MAJOR_WORKFORCE_SCORE_FLOOR)
    return raw


def headline_adjustment(headline: str) -> int:
    """Deterministic rank nudge when the LLM compresses scores."""
    if _META_ANALYSIS.search(headline):
        return -1
    if _AGENT_DEMO_STUNT.search(headline):
        return -2
    adj = 0
    if editorial_family(headline) == "workforce":
        adj += 1
    if _OPEN_MODEL.search(headline):
        adj += 1
    if _CODING_AGENT.search(headline):
        adj += 1
    if _PRODUCTION_ML.search(headline):
        adj += 1
    return adj


def effective_significance(cluster: StoryCluster, entries: list[FeedEntry]) -> int:
    return editorial_raw_significance(cluster, entries) + headline_adjustment(
        _headline(cluster, entries)
    )


def _workforce_subrank(headline: str) -> int:
    if _WORKFORCE_ROUNDUP.search(headline):
        return 1
    return 0


def _family_subrank(headline: str) -> int:
    """Higher subrank sorts later when effective scores tie."""
    family = editorial_family(headline)
    if family == "workforce":
        return _workforce_subrank(headline)
    if family == "regulatory_commentary":
        return 1
    return 0


def editorial_tier(significance: int) -> str:
    if significance >= TIER_A_MIN:
        return "A"
    if significance >= TIER_B_MIN:
        return "B"
    return "C"


def is_builder_relevant(cluster: StoryCluster, entries: list[FeedEntry]) -> bool:
    headline = _headline(cluster, entries)
    if is_consumer_beta_noise(headline):
        return False
    if is_consumer_hardware_noise(headline):
        return False
    raw = editorial_raw_significance(cluster, entries)
    if raw < MIN_SIGNIFICANCE:
        return False
    if raw >= TIER_B_MIN:
        return True
    return cluster.ai_relevant


def _topic_priority(cluster: StoryCluster, entries: list[FeedEntry]) -> int:
    topics = [entries[i].topic for i in cluster.entry_indices if i < len(entries)]
    if not topics:
        return 99
    return min(TOPIC_RANK.get(t, 99) for t in topics)


def _rank_key(cluster: StoryCluster, entries: list[FeedEntry]) -> tuple[int, int, int, int]:
    headline = _headline(cluster, entries)
    return (
        -effective_significance(cluster, entries),
        _family_subrank(headline),
        _topic_priority(cluster, entries),
        min(cluster.entry_indices),
    )


def _primary_source(cluster: StoryCluster, entries: list[FeedEntry]) -> str:
    for i in cluster.entry_indices:
        if i < len(entries):
            return entries[i].source.lower()
    return ""


def _headline(cluster: StoryCluster, entries: list[FeedEntry]) -> str:
    for i in cluster.entry_indices:
        if i < len(entries):
            return entries[i].title
    return "?"


def _cluster_key(cluster: StoryCluster) -> tuple[int, ...]:
    return tuple(sorted(cluster.entry_indices))


def rank_selection_candidates(
    raw: list[StoryCluster],
    entries: list[FeedEntry],
    *,
    max_candidates: int,
) -> list[StoryCluster]:
    """Return clusters in editorial pick order (tier reservation, caps, rank nudges).

    Used for the initial digest slots and for extract backfill: runner-ups only
    appear after earlier picks and must pass the same gates.
    """
    valid_range = range(len(entries))
    used: set[int] = set()
    selected: list[StoryCluster] = []
    chosen: set[tuple[int, ...]] = set()
    family_counts: dict[str, int] = {}
    geo_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}

    def available(cluster: StoryCluster) -> list[int]:
        return [i for i in cluster.entry_indices if i in valid_range and i not in used]

    def try_add(cluster: StoryCluster) -> bool:
        key = _cluster_key(cluster)
        if key in chosen:
            return False
        indices = available(cluster)
        if not indices:
            return False
        headline = _headline(cluster, entries)
        raw = editorial_raw_significance(cluster, entries)
        effective = effective_significance(cluster, entries)
        if is_consumer_beta_noise(headline):
            logger.info("Triage CUT (consumer beta, %d): %s", cluster.significance, headline)
            return False
        if is_consumer_hardware_noise(headline):
            logger.info(
                "Triage CUT (consumer hardware, %d): %s",
                cluster.significance,
                headline,
            )
            return False
        if not is_builder_relevant(cluster, entries):
            logger.info(
                "Triage CUT (not AI-relevant, %d): %s",
                raw,
                headline,
            )
            return False
        if raw < MIN_SIGNIFICANCE:
            logger.info("Triage CUT (score %d): %s", raw, headline)
            return False
        family = editorial_family(headline)
        if family is not None:
            limit = FAMILY_LIMITS.get(family, 0)
            if limit and family_counts.get(family, 0) >= limit:
                logger.info(
                    "Triage CUT (family %s full, %d): %s",
                    family,
                    cluster.significance,
                    headline,
                )
                return False
        geo = editorial_geo_bucket(headline)
        if geo is not None:
            limit = GEO_LIMITS.get(geo, 0)
            if limit and geo_counts.get(geo, 0) >= limit:
                logger.info(
                    "Triage CUT (geo %s full, %d): %s",
                    geo,
                    cluster.significance,
                    headline,
                )
                return False
        source = _primary_source(cluster, entries)
        if source and source_counts.get(source, 0) >= MAX_STORIES_PER_SOURCE:
            logger.info(
                "Triage CUT (source %s full, %d): %s",
                source,
                cluster.significance,
                headline,
            )
            return False
        if len(selected) >= max_candidates:
            logger.info(
                "Triage CUT (over limit, eff %d, raw %d): %s",
                effective,
                cluster.significance,
                headline,
            )
            return False
        used.update(indices)
        chosen.add(key)
        if family is not None:
            family_counts[family] = family_counts.get(family, 0) + 1
        if geo is not None:
            geo_counts[geo] = geo_counts.get(geo, 0) + 1
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1
        selected.append(cluster.model_copy(update={"entry_indices": indices}))
        eff_tier = editorial_tier(effective)
        if raw != cluster.significance and effective != raw:
            score_note = f"{cluster.significance}->{raw}->{effective}"
        elif raw != cluster.significance:
            score_note = f"{cluster.significance}->{raw}"
        elif effective != cluster.significance:
            score_note = f"{cluster.significance}->{effective}"
        else:
            score_note = str(cluster.significance)
        geo_note = f", {geo}" if geo else ""
        logger.info(
            "Triage KEPT (score %s, Tier %s%s%s): %s | %s",
            score_note,
            eff_tier,
            f", {family}" if family else "",
            geo_note,
            headline,
            cluster.reason,
        )
        return True

    eligible = [
        c
        for c in raw
        if is_builder_relevant(c, entries)
        and editorial_raw_significance(c, entries) >= MIN_SIGNIFICANCE
        and any(i in valid_range for i in c.entry_indices)
    ]

    tier_a = sorted(
        [c for c in eligible if effective_significance(c, entries) >= TIER_A_MIN],
        key=lambda c: _rank_key(c, entries),
    )
    for cluster in tier_a[:MAX_TIER_A_SLOTS]:
        try_add(cluster)

    remaining = sorted(
        [c for c in eligible if _cluster_key(c) not in chosen],
        key=lambda c: _rank_key(c, entries),
    )
    for cluster in remaining:
        if len(selected) >= max_candidates:
            break
        try_add(cluster)

    return selected


def select_clusters(
    raw: list[StoryCluster],
    entries: list[FeedEntry],
    max_stories: int,
) -> list[StoryCluster]:
    """Select up to max_stories with tier reservation, family caps, and rank nudges."""
    return rank_selection_candidates(raw, entries, max_candidates=max_stories)
