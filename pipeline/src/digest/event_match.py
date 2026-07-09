"""Deterministic duplicate-outlet grouping for triage.

Only merges headlines that describe the same specific news event (precision over
recall). Vendor or product keywords alone never merge — e.g. two unrelated
"Claude" stories stay separate. Multi-member clusters are split when any member
does not match the anchor headline.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from .models import ClusterGroup, FeedEntry, StoryCluster

logger = logging.getLogger(__name__)

MAX_EVENT_CLUSTER_MEMBERS = 4

_COVERAGE_PREFIX = re.compile(
    r"^(?:coverage|analysis|explainer|recap|roundup|watch|deep\s+dive|opinion)\s*:\s*",
    re.IGNORECASE,
)

# Hyphenated research/product IDs (j-lens, co-pilot-style names, versioned slugs).
_COMPOUND_SIGNATURE = re.compile(
    r"\b[a-z0-9]{1,8}[-_][a-z0-9][a-z0-9\-]*",
    re.IGNORECASE,
)

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
        "story",
        "stories",
        "update",
        "updates",
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
    r"gpt[\s-]?live|"
    r"glm[\d.\-]+|"
    r"sol[\s-]?ultra|"
    r"mechanical[\s-]?turk"
    r")\b",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[a-z0-9]+")

_FIRST_PARTY_DOMAINS = frozenset(
    {
        "anthropic.com",
        "openai.com",
        "blog.google",
        "ai.googleblog.com",
        "deepmind.google",
        "research.google",
        "ai.meta.com",
        "about.fb.com",
        "microsoft.com",
        "blogs.microsoft.com",
        "research.microsoft.com",
        "nvidia.com",
        "developer.nvidia.com",
    }
)

_NEWS_OUTLET_DOMAINS = frozenset(
    {
        "venturebeat.com",
        "techcrunch.com",
        "arstechnica.com",
        "the-verge.com",
        "theverge.com",
        "wired.com",
        "the-decoder.com",
        "technologyreview.com",
        "theregister.com",
        "ieee.org",
        "spectrum.ieee.org",
    }
)

_DOMAIN_VENDOR: dict[str, str] = {
    "anthropic.com": "anthropic",
    "openai.com": "openai",
    "blog.google": "google",
    "ai.googleblog.com": "google",
    "deepmind.google": "google",
    "research.google": "google",
    "ai.meta.com": "meta",
    "about.fb.com": "meta",
    "microsoft.com": "microsoft",
    "blogs.microsoft.com": "microsoft",
    "research.microsoft.com": "microsoft",
    "nvidia.com": "nvidia",
    "developer.nvidia.com": "nvidia",
}


def _domain(url: str) -> str:
    return urlsplit(url).netloc.removeprefix("www.")


def _is_first_party_url(url: str) -> bool:
    domain = _domain(url)
    if domain in _FIRST_PARTY_DOMAINS:
        return True
    return any(domain.endswith(f".{suffix}") for suffix in _FIRST_PARTY_DOMAINS)


def _is_news_outlet_url(url: str) -> bool:
    domain = _domain(url)
    if domain in _NEWS_OUTLET_DOMAINS:
        return True
    return any(domain.endswith(f".{suffix}") for suffix in _NEWS_OUTLET_DOMAINS)


def _vendor_for_first_party(url: str) -> str | None:
    domain = _domain(url)
    if domain in _DOMAIN_VENDOR:
        return _DOMAIN_VENDOR[domain]
    for suffix, vendor in _DOMAIN_VENDOR.items():
        if domain.endswith(f".{suffix}"):
            return vendor
    return None


def _url_path_tokens(url: str) -> set[str]:
    path = urlsplit(url).path.lower().strip("/")
    tokens: set[str] = set()
    for segment in path.split("/"):
        if segment in {"research", "blog", "news", "technology", "engineering"}:
            continue
        tokens |= _title_tokens(segment.replace("-", " "))
        tokens |= _compound_signatures(segment)
        for part in re.split(r"[-_]", segment):
            if len(part) >= 4 and part not in _GENERIC_TOKENS:
                tokens.add(part)
    return tokens


def _entry_match_tokens(entry: FeedEntry) -> set[str]:
    tokens = _title_tokens(entry.title)
    tokens |= _url_path_tokens(entry.url)
    preview = entry.preview(120)
    if preview and "no useful rss preview" not in preview.lower():
        tokens |= _title_tokens(preview)
    return tokens


def _title_mentions_vendor(title: str, vendor: str) -> bool:
    return any(token == vendor or token.startswith(vendor) for token in _title_tokens(title))


def _news_outlets_same_event(a: FeedEntry, b: FeedEntry) -> bool:
    """Two news outlets covering the same vendor product launch."""
    if not (_is_news_outlet_url(a.url) and _is_news_outlet_url(b.url)):
        return False
    ta, tb = _entry_match_tokens(a), _entry_match_tokens(b)
    if not ((ta & _VENDOR_ONLY) & (tb & _VENDOR_ONLY)):
        return False
    distinctive = _distinctive_overlap(ta, tb)
    if len(distinctive) >= 2:
        return True
    sig_a = _event_signatures(a.title) | _compound_signatures(a.url)
    sig_b = _event_signatures(b.title) | _compound_signatures(b.url)
    if sig_a & sig_b:
        return True
    return len(distinctive) >= 1


def _primary_coverage_same_event(primary: FeedEntry, coverage: FeedEntry) -> bool:
    """Vendor research/blog post paired with news coverage of the same release."""
    if not _is_first_party_url(primary.url) or not _is_news_outlet_url(coverage.url):
        return False
    vendor = _vendor_for_first_party(primary.url)
    if vendor is None or not _title_mentions_vendor(coverage.title, vendor):
        return False
    primary_tokens = _entry_match_tokens(primary)
    coverage_tokens = _entry_match_tokens(coverage)
    distinctive = _distinctive_overlap(primary_tokens, coverage_tokens)
    if len(distinctive) >= 2:
        return True
    if len(distinctive) >= 1:
        return True
    return False


def entries_same_event(a: FeedEntry, b: FeedEntry) -> bool:
    """True when two feed entries cover the same specific news event."""
    if titles_same_event(a.title, b.title):
        return True
    if _news_outlets_same_event(a, b):
        return True
    return _primary_coverage_same_event(a, b) or _primary_coverage_same_event(b, a)


def _normalize_title(title: str) -> str:
    """Strip editorial prefixes so coverage headlines compare to primaries."""
    return _COVERAGE_PREFIX.sub("", title.strip()).strip()


def _title_tokens(title: str) -> set[str]:
    return {
        w
        for w in _TOKEN.findall(_normalize_title(title).lower())
        if len(w) >= 2 and w not in _GENERIC_TOKENS
    }


def _compound_signatures(title: str) -> set[str]:
    normalized = _normalize_title(title).lower()
    return {m.group().replace("_", "-") for m in _COMPOUND_SIGNATURE.finditer(normalized)}


def _event_signatures(title: str) -> set[str]:
    normalized = _normalize_title(title)
    sigs = {m.group().lower().replace(" ", "") for m in _EVENT_SIGNATURE.finditer(normalized)}
    sigs |= _compound_signatures(normalized)
    return sigs


def _distinctive_overlap(ta: set[str], tb: set[str], *, min_len: int = 4) -> set[str]:
    return {w for w in (ta & tb) if len(w) >= min_len and w not in _VENDOR_ONLY}


def titles_same_event(a: str, b: str) -> bool:
    """True when two headlines cover the same specific news event."""
    a, b = _normalize_title(a), _normalize_title(b)
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
    return len(overlap) / len(union) >= 0.4 and len(distinctive) >= 2


def clusters_share_event(
    left: StoryCluster,
    right: StoryCluster,
    entries: list[FeedEntry],
) -> bool:
    """True when any member in left matches any member in right."""
    for i in left.entry_indices:
        for j in right.entry_indices:
            if i < len(entries) and j < len(entries):
                if entries_same_event(entries[i], entries[j]):
                    return True
    return False


def cluster_should_merge_with(
    existing: StoryCluster,
    candidate: StoryCluster,
    entries: list[FeedEntry],
) -> bool:
    """True when candidate matches the existing cluster anchor (no transitive chaining)."""
    existing_indices = [i for i in existing.entry_indices if i < len(entries)]
    candidate_indices = [i for i in candidate.entry_indices if i < len(entries)]
    if not existing_indices or not candidate_indices:
        return False
    anchor = entries[existing_indices[0]]
    return any(entries_same_event(anchor, entries[j]) for j in candidate_indices)


def assert_unique_event_clusters(
    clusters: list[StoryCluster],
    entries: list[FeedEntry],
) -> None:
    """Raise when two selected clusters would publish the same news event."""
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            ai = clusters[i].entry_indices[0] if clusters[i].entry_indices else -1
            aj = clusters[j].entry_indices[0] if clusters[j].entry_indices else -1
            if ai < 0 or aj < 0 or ai >= len(entries) or aj >= len(entries):
                continue
            if entries_same_event(entries[ai], entries[aj]):
                left = entries[ai].title
                right = entries[aj].title
                raise ValueError(
                    f"Duplicate event in selected clusters: {left!r} vs {right!r}"
                )


def cluster_is_coherent(cluster: StoryCluster, entries: list[FeedEntry]) -> bool:
    """True when every member headline describes the same event as the anchor."""
    indices = [i for i in cluster.entry_indices if i < len(entries)]
    if len(indices) <= 1:
        return True
    anchor = entries[indices[0]]
    return all(entries_same_event(anchor, entries[i]) for i in indices[1:])


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


def coerce_coherent_clusters(
    clusters: list[StoryCluster],
    entries: list[FeedEntry],
) -> list[StoryCluster]:
    """Keep story count stable by dropping non-anchor members from bad clusters."""
    coerced: list[StoryCluster] = []
    for cluster in clusters:
        if cluster_is_coherent(cluster, entries):
            coerced.append(cluster)
            continue
        anchor = cluster.entry_indices[0]
        headline = entries[anchor].title if anchor < len(entries) else "?"
        logger.warning(
            "Coercing incoherent cluster to anchor-only (%d members): %s",
            len(cluster.entry_indices),
            headline[:80],
        )
        coerced.append(cluster.model_copy(update={"entry_indices": [anchor]}))
    return coerced


def _groups_share_event(
    left: ClusterGroup,
    right: ClusterGroup,
    entries: list[FeedEntry],
) -> bool:
    for i in left.entry_indices:
        for j in right.entry_indices:
            if i < len(entries) and j < len(entries):
                if entries_same_event(entries[i], entries[j]):
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
