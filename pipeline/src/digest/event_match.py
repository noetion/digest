"""Deterministic duplicate-outlet grouping for triage.

Only merges headlines that describe the same specific news event (precision over
recall). Vendor or product keywords alone never merge — e.g. two unrelated
"Claude" stories stay separate. Multi-member clusters are split when any member
does not match the anchor headline.
"""

from __future__ import annotations

import logging
import re

from .models import ClusterGroup, FeedEntry, StoryCluster

logger = logging.getLogger(__name__)

_GENERIC_TOKENS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "will",
        "says",
        "said",
        "new",
        "about",
        "after",
        "into",
        "over",
        "its",
        "has",
        "have",
        "are",
        "was",
        "were",
        "can",
        "not",
        "all",
        "out",
        "how",
        "why",
        "what",
        "when",
        "who",
        "their",
        "they",
        "than",
        "more",
        "also",
        "just",
        "now",
        "may",
        "open",
        "source",
        "report",
        "reports",
        "reportedly",
        "tech",
        "ai",
        "model",
        "models",
        "company",
        "world",
        "first",
        "make",
        "take",
        "using",
        "use",
        "launch",
        "launches",
        "released",
        "release",
        "announces",
        "announced",
        "news",
        "day",
        "million",
        "billion",
        "employees",
        "employee",
        "layoff",
        "layoffs",
        "cuts",
        "cut",
        "to",
        "up",
        "of",
        "in",
        "on",
        "at",
        "as",
        "by",
        "or",
        "an",
        "is",
        "it",
        "be",
        "do",
        "if",
        "so",
        "no",
        "we",
        "our",
        "your",
        "code",
        "users",
        "user",
        "secret",
        "native",
    }
)

_VENDOR_ONLY = frozenset(
    {
        "microsoft",
        "google",
        "amazon",
        "apple",
        "meta",
        "openai",
        "anthropic",
        "nvidia",
        "tencent",
        "alibaba",
        "zhipu",
    }
)

# Versioned model IDs and named products only — never bare vendor/tool names.
_EVENT_SIGNATURE = re.compile(
    r"\b(?:"
    r"hy\d+|"
    r"gpt[\d.\-]+|"
    r"glm[\d.\-]+|"
    r"sol[\s-]?ultra|"
    r"mechanical[\s-]?turk"
    r")\b",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[a-z0-9]+")


def _title_tokens(title: str) -> set[str]:
    return {
        w
        for w in _TOKEN.findall(title.lower())
        if len(w) >= 2 and w not in _GENERIC_TOKENS
    }


def _event_signatures(title: str) -> set[str]:
    return {m.group().lower().replace(" ", "") for m in _EVENT_SIGNATURE.finditer(title)}


def _distinctive_overlap(ta: set[str], tb: set[str]) -> set[str]:
    return {w for w in (ta & tb) if len(w) >= 5 and w not in _VENDOR_ONLY}


def titles_same_event(a: str, b: str) -> bool:
    """True when two headlines cover the same specific news event."""
    sig_a, sig_b = _event_signatures(a), _event_signatures(b)
    if sig_a & sig_b:
        return True

    ta, tb = _title_tokens(a), _title_tokens(b)
    if "mechanical" in ta and "turk" in ta and "mechanical" in tb and "turk" in tb:
        return True

    distinctive = _distinctive_overlap(ta, tb)
    if len(distinctive) >= 2:
        return True

    overlap = ta & tb
    if not overlap or not distinctive:
        return False

    union = ta | tb
    return len(overlap) / len(union) >= 0.4 and len(distinctive) >= 1


def cluster_is_coherent(cluster: StoryCluster, entries: list[FeedEntry]) -> bool:
    """True when every member headline describes the same event as the anchor."""
    indices = [i for i in cluster.entry_indices if i < len(entries)]
    if len(indices) <= 1:
        return True
    anchor = entries[indices[0]].title
    return all(titles_same_event(anchor, entries[i].title) for i in indices[1:])


def split_incoherent_clusters(
    clusters: list[StoryCluster],
    entries: list[FeedEntry],
) -> list[StoryCluster]:
    """Split multi-member clusters that would attach wrong sources downstream."""
    split: list[StoryCluster] = []
    for cluster in clusters:
        if cluster_is_coherent(cluster, entries):
            split.append(cluster)
            continue
        headline = entries[cluster.entry_indices[0]].title if cluster.entry_indices else "?"
        logger.warning(
            "Splitting incoherent cluster (%d members): %s",
            len(cluster.entry_indices),
            headline[:80],
        )
        for i in cluster.entry_indices:
            split.append(cluster.model_copy(update={"entry_indices": [i]}))
    return split


def _groups_share_event(
    left: ClusterGroup,
    right: ClusterGroup,
    entries: list[FeedEntry],
) -> bool:
    for i in left.entry_indices:
        for j in right.entry_indices:
            if i < len(entries) and j < len(entries):
                if titles_same_event(entries[i].title, entries[j].title):
                    return True
    return False


def _union_find_merge(
    groups: list[ClusterGroup],
    entries: list[FeedEntry],
    max_members: int,
) -> list[ClusterGroup]:
    n = len(groups)
    if n <= 1:
        return groups

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _groups_share_event(groups[i], groups[j], entries):
                combined = set(groups[i].entry_indices) | set(groups[j].entry_indices)
                if len(combined) <= max_members:
                    union(i, j)

    buckets: dict[int, list[int]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)

    merged: list[ClusterGroup] = []
    for member_indices in buckets.values():
        if len(member_indices) == 1:
            merged.append(groups[member_indices[0]])
            continue
        all_entry_indices: list[int] = []
        events: list[str] = []
        for gi in member_indices:
            all_entry_indices.extend(groups[gi].entry_indices)
            events.append(groups[gi].event)
        merged.append(
            ClusterGroup(
                entry_indices=sorted(set(all_entry_indices)),
                event=events[0],
            )
        )
    return merged


def singleton_groups(entries: list[FeedEntry]) -> list[ClusterGroup]:
    """One group per candidate — the only starting point for duplicate merging."""
    return [
        ClusterGroup(entry_indices=[i], event=entries[i].title)
        for i in range(len(entries))
    ]


def refine_cluster_groups(
    groups: list[ClusterGroup],
    entries: list[FeedEntry],
    *,
    max_members: int,
) -> list[ClusterGroup]:
    """Merge groups that cover the same event (duplicate outlet coverage only)."""
    if not groups:
        return groups
    before = len(groups)
    refined = _union_find_merge(groups, entries, max_members)
    if len(refined) < before:
        logger.info(
            "Duplicate merge: %d singleton groups -> %d event clusters",
            before,
            len(refined),
        )
    return refined
