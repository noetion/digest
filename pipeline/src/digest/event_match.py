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
_DATE_PATH_SEGMENT = re.compile(r"^(?:20\d{2}|\d{1,2})$")

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
        if _DATE_PATH_SEGMENT.match(segment):
            continue
        tokens |= _title_tokens(segment.replace("-", " "))
        tokens |= _compound_signatures(segment)
        for part in re.split(r"[-_]", segment):
            if len(part) >= 4 and part not in _GENERIC_TOKENS:
                tokens.add(part)
    return tokens


def _entry_match_tokens(entry: FeedEntry) -> set[str]:
    """Headline and URL tokens for event matching (never full article text)."""
    tokens = _title_tokens(entry.title)
    tokens |= _url_path_tokens(entry.url)
    return tokens


_VENDOR_PRODUCT_TOKENS: dict[str, frozenset[str]] = {
    "anthropic": frozenset({"fable", "sonnet", "claude", "opus"}),
    "openai": frozenset({"chatgpt", "codex", "dalle", "sora"}),
}
_VENDOR_PRODUCT_ONLY = frozenset().union(*_VENDOR_PRODUCT_TOKENS.values())

_ROLLOUT_MARKERS = frozenset(
    {
        "launch",
        "launches",
        "released",
        "rollout",
        "introduces",
        "introduced",
        "announces",
        "announced",
        "ships",
        "shipped",
        "preferred",
        "copilot",
        "partnership",
        "unveils",
        "unveiled",
        "debuts",
    }
)

_GENERIC_PATH_SIGNATURE = re.compile(
    r"^gpt-\d|^glm-\d|^claude-\d|^grok-\d|^fable-\d|^sonnet-\d",
    re.IGNORECASE,
)


def _vendors_in_title(title: str) -> set[str]:
    return _title_tokens(title) & _VENDOR_ONLY


def _is_generic_model_sig(sig: str) -> bool:
    normalized = sig.lower().replace(".", "-")
    return bool(_GENERIC_PATH_SIGNATURE.match(normalized))


def _meaningful_event_signatures(text: str) -> set[str]:
    return {sig for sig in _event_signatures(text) if not _is_generic_model_sig(sig)}


def _headline_is_rollout_angle(title: str) -> bool:
    raw = {w for w in _TOKEN.findall(_normalize_title(title).lower()) if len(w) >= 2}
    return bool(raw & _ROLLOUT_MARKERS)


def _substantive_overlap(ta: set[str], tb: set[str]) -> set[str]:
    return _distinctive_overlap(ta, tb) - _VENDOR_PRODUCT_ONLY


def _meaningful_path_signatures(url: str) -> set[str]:
    sigs = _url_path_event_signatures(url)
    return {sig for sig in sigs if not _is_generic_model_sig(sig)}


def _vendor_subject(title: str) -> str | None:
    vendors = _vendors_in_title(title)
    if not vendors:
        return None
    return next(iter(sorted(vendors)))


def _cross_vendor_product_confusion(
    a: str,
    b: str,
    distinctive: set[str],
) -> bool:
    """Block merges where one headline is vendor news and the other only cites its product."""
    va, vb = _vendors_in_title(a), _vendors_in_title(b)
    if va and vb and not (va & vb):
        return True
    for vendor, products in _VENDOR_PRODUCT_TOKENS.items():
        if not (distinctive & products):
            continue
        if (vendor in va) != (vendor in vb):
            return True
    return False


_MODEL_ID = re.compile(
    r"\b(gpt|claude|gemini|glm|grok|fable|sonnet|opus|hy|sol|chatgpt)[\s\-_.]*(\d+(?:[.\-]\d+)?)",
    re.IGNORECASE,
)


def _model_ids_from_text(text: str) -> set[str]:
    ids: set[str] = set()
    for match in _MODEL_ID.finditer(text.lower()):
        family = match.group(1).lower()
        if family == "chatgpt":
            family = "gpt"
        version = match.group(2).replace(".", "-")
        ids.add(f"{family}-{version}")
    return ids


def _url_path_event_signatures(url: str) -> set[str]:
    """Product/event signatures from URL path only (not the outlet domain)."""
    path = urlsplit(url).path
    sigs = _event_signatures(path)
    sigs |= _compound_signatures(path)
    return sigs


def _shared_vendor_model_release(a: FeedEntry, b: FeedEntry) -> bool:
    """Same vendor shipping the same model version, covered from different angles."""
    ids_a = _model_ids_from_text(a.title) | _model_ids_from_text(urlsplit(a.url).path)
    ids_b = _model_ids_from_text(b.title) | _model_ids_from_text(urlsplit(b.url).path)
    if not (ids_a & ids_b):
        return False
    vendors_a = {v for v in _VENDOR_ONLY if _title_mentions_vendor(a.title, v)} | (
        _entry_match_tokens(a) & _VENDOR_ONLY
    )
    vendors_b = {v for v in _VENDOR_ONLY if _title_mentions_vendor(b.title, v)} | (
        _entry_match_tokens(b) & _VENDOR_ONLY
    )
    if not (vendors_a & vendors_b):
        return False
    distinctive = _distinctive_overlap(_title_tokens(a.title), _title_tokens(b.title))
    if _cross_vendor_product_confusion(a.title, b.title, distinctive):
        return False
    rollout_a = _headline_is_rollout_angle(a.title)
    rollout_b = _headline_is_rollout_angle(b.title)
    if rollout_a and rollout_b:
        return True
    if rollout_a or rollout_b:
        return False
    return len(_substantive_overlap(_title_tokens(a.title), _title_tokens(b.title))) >= 2


def _title_mentions_vendor(title: str, vendor: str) -> bool:
    return any(token == vendor or token.startswith(vendor) for token in _title_tokens(title))


def _news_outlets_same_event(a: FeedEntry, b: FeedEntry) -> bool:
    """Two news outlets covering the same vendor product launch."""
    if not (_is_news_outlet_url(a.url) and _is_news_outlet_url(b.url)):
        return False
    ta, tb = _entry_match_tokens(a), _entry_match_tokens(b)
    if not ((ta & _VENDOR_ONLY) & (tb & _VENDOR_ONLY)):
        return False
    distinctive = _substantive_overlap(ta, tb)
    if len(distinctive) >= 2:
        return True
    sig_a = _meaningful_event_signatures(a.title) | _meaningful_path_signatures(a.url)
    sig_b = _meaningful_event_signatures(b.title) | _meaningful_path_signatures(b.url)
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
    if _shared_vendor_model_release(a, b):
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
    return {
        w
        for w in (ta & tb)
        if len(w) >= min_len
        and w not in _VENDOR_ONLY
        and not _DATE_PATH_SEGMENT.match(w)
    }


def titles_same_event(a: str, b: str) -> bool:
    """True when two headlines cover the same specific news event."""
    a, b = _normalize_title(a), _normalize_title(b)
    sig_a, sig_b = _meaningful_event_signatures(a), _meaningful_event_signatures(b)
    if sig_a & sig_b:
        return True

    ta, tb = _title_tokens(a), _title_tokens(b)
    if "mechanical" in ta and "turk" in ta and "mechanical" in tb and "turk" in tb:
        return True

    distinctive = _distinctive_overlap(ta, tb)
    if len(distinctive) >= 2:
        if _cross_vendor_product_confusion(a, b, distinctive):
            return False
        return True

    overlap = ta & tb
    if not overlap or not distinctive:
        return False

    union = ta | tb
    if len(overlap) / len(union) >= 0.4 and len(distinctive) >= 2:
        return not _cross_vendor_product_confusion(a, b, distinctive)
    return False


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


def merge_duplicate_event_clusters(
    clusters: list[StoryCluster],
    entries: list[FeedEntry],
) -> list[StoryCluster]:
    """Fold selected clusters that cover the same event into one published story."""
    merged: list[StoryCluster] = []
    for cluster in clusters:
        absorbed = False
        for pos, existing in enumerate(merged):
            ai = existing.entry_indices[0] if existing.entry_indices else -1
            bi = cluster.entry_indices[0] if cluster.entry_indices else -1
            if ai < 0 or bi < 0 or ai >= len(entries) or bi >= len(entries):
                continue
            if not entries_same_event(entries[ai], entries[bi]):
                continue
            combined = sorted(set(existing.entry_indices + cluster.entry_indices))
            if len(combined) > MAX_EVENT_CLUSTER_MEMBERS:
                logger.info(
                    "Dropping duplicate cluster (member cap): %s",
                    entries[bi].title[:80],
                )
                absorbed = True
                break
            logger.info(
                "Merging duplicate event cluster: %s",
                entries[bi].title[:80],
            )
            merged[pos] = existing.model_copy(
                update={
                    "entry_indices": combined,
                    "significance": max(existing.significance, cluster.significance),
                    "ai_relevant": existing.ai_relevant or cluster.ai_relevant,
                }
            )
            absorbed = True
            break
        if not absorbed:
            merged.append(cluster)
    return merged


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
