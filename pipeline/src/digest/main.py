"""Pipeline orchestrator: python -m digest.main

Stages: fetch feeds -> dedup -> triage (cheap) -> extract full text (winners
only) -> synthesize -> render markdown+JSON -> mark seen -> optional Dev.to
cross-post. CI commits the rendered files, which triggers the site deploy.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import UTC, date, datetime

from openai import OpenAI

from .config import CONTENT_DIR, DRY_RUN_OUT_DIR, SEEN_STATE_PATH, load_settings
from .costs import CostTracker
from .dedupe import SeenState, filter_unseen
from .event_match import assert_unique_event_clusters, coerce_coherent_clusters
from .extract import enrich_with_full_text
from .feeds import fetch_all_feeds
from .models import FeedEntry, StoryCluster
from .publish import crosspost_to_devto
from .quality import ABS_MIN_STORIES, QualityGateError, check_quality
from .render import write_post
from .synthesize import attach_cluster_sources, synthesize
from .triage import triage

logger = logging.getLogger(__name__)


def _target_date() -> date:
    raw = os.environ.get("DIGEST_DATE", "").strip()
    if raw:
        return date.fromisoformat(raw)
    return datetime.now(tz=UTC).date()


def _allow_overwrite() -> bool:
    return os.environ.get("DIGEST_OVERWRITE", "").strip().lower() in {"1", "true", "yes"}


def cluster_member_urls(
    clusters: list[StoryCluster],
    entries: list[FeedEntry],
) -> list[str]:
    """URLs for articles in the given clusters (used for seen-state updates)."""
    return [entries[idx].url for cluster in clusters for idx in cluster.entry_indices]


def remap_clusters(
    clusters: list[StoryCluster],
    candidates: list[FeedEntry],
    extracted: list[FeedEntry],
) -> list[StoryCluster]:
    """Re-map cluster indices from the candidate list onto the extracted list.

    Extraction can drop entries (paywalls, empty bodies), which shifts the
    positions of everything after the dropped entry, so members are matched by
    URL rather than by arithmetic on the original indices. Clusters left empty
    are dropped.
    """
    extracted_pos = {e.url: i for i, e in enumerate(extracted)}
    remapped: list[StoryCluster] = []
    for cluster in clusters:
        kept = [
            extracted_pos[candidates[i].url]
            for i in cluster.entry_indices
            if candidates[i].url in extracted_pos
        ]
        if kept:
            remapped.append(cluster.model_copy(update={"entry_indices": kept}))
    return remapped


def _headline_for_cluster(cluster: StoryCluster, candidates: list[FeedEntry]) -> str:
    for idx in cluster.entry_indices:
        if idx < len(candidates):
            return candidates[idx].title
    return "?"


def extract_selected_clusters(
    ranked: list[StoryCluster],
    candidates: list[FeedEntry],
    max_stories: int,
    max_words: int,
) -> tuple[list[FeedEntry], list[StoryCluster]]:
    """Extract ranked clusters in order; backfill from reserve when extract fails."""
    winners: list[FeedEntry] = []
    extracted_urls: set[str] = set()
    published: list[StoryCluster] = []

    for rank_pos, cluster in enumerate(ranked):
        if len(published) >= max_stories:
            break
        members = [candidates[i] for i in cluster.entry_indices]
        to_fetch = [m for m in members if m.url not in extracted_urls]
        if to_fetch:
            for entry in enrich_with_full_text(to_fetch, max_words):
                extracted_urls.add(entry.url)
                winners.append(entry)
        remapped = remap_clusters([cluster], candidates, winners)
        if not remapped:
            logger.warning(
                "Extract SKIP (no usable text): %s",
                _headline_for_cluster(cluster, candidates),
            )
            continue
        label = "BACKFILL" if rank_pos >= max_stories else "KEPT"
        logger.info(
            "Extract %s (%d/%d): %s",
            label,
            len(published) + 1,
            max_stories,
            _headline_for_cluster(cluster, candidates),
        )
        published.append(remapped[0])

    return winners, published


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    start = time.monotonic()
    settings = load_settings()
    today = _target_date()
    content_dir = DRY_RUN_OUT_DIR if settings.dry_run else CONTENT_DIR

    digest_path = CONTENT_DIR / f"{today.isoformat()}.md"
    if digest_path.exists() and not settings.dry_run and not _allow_overwrite():
        logger.info("Digest for %s already published; nothing to do.", today)
        return 0

    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")
        return 1

    # --- Acquisition ---
    candidates = fetch_all_feeds()
    logger.info("Fetched %d fresh candidates across all feeds", len(candidates))

    state = SeenState(SEEN_STATE_PATH)
    candidates = filter_unseen(candidates, state)
    logger.info("%d candidates after dedup", len(candidates))
    if not candidates:
        logger.warning("No new articles today; skipping digest.")
        return 0

    # --- LLM stage A: cheap triage on previews only ---
    client = OpenAI(api_key=settings.openai_api_key)
    tracker = CostTracker(cap_usd=settings.daily_cost_cap_usd)
    clusters = triage(client, candidates, settings.max_stories, tracker)
    if not clusters:
        if len(candidates) >= ABS_MIN_STORIES:
            logger.error(
                "Triage selected no stories from %d candidates; aborting.",
                len(candidates),
            )
            return 1
        logger.warning("Triage selected no stories; skipping digest.")
        return 0

    winners, remapped = extract_selected_clusters(
        clusters,
        candidates,
        settings.max_stories,
        settings.max_article_words,
    )
    if not remapped:
        logger.error("All ranked articles failed extraction; aborting.")
        return 1
    if len(remapped) < ABS_MIN_STORIES:
        logger.warning(
            "Only %d stories after extraction (need %d); skipping digest. "
            "Seen state not updated.",
            len(remapped),
            ABS_MIN_STORIES,
        )
        return 0
    if len(remapped) < settings.max_stories:
        logger.warning(
            "Published %d/%d stories after extract backfill exhausted reserve",
            len(remapped),
            settings.max_stories,
        )
    logger.info("Extracted full text for %d winning articles", len(winners))

    remapped = coerce_coherent_clusters(remapped, winners)

    try:
        assert_unique_event_clusters(remapped, winners)
    except ValueError as exc:
        raise QualityGateError(str(exc)) from exc

    # --- LLM stage B: synthesis ---
    date_str = today.strftime("%A, %B %d, %Y")
    digest = synthesize(client, date_str, winners, remapped, tracker)
    try:
        digest = attach_cluster_sources(digest, winners, remapped)
    except ValueError as exc:
        raise QualityGateError(str(exc)) from exc
    check_quality(digest, expected_story_count=len(remapped))

    # --- Render + state ---
    md_path, json_path = write_post(digest, today, content_dir)
    logger.info("Wrote %s and %s", md_path, json_path)

    if not settings.dry_run:
        # Only mark URLs from clusters that actually published. Rejected
        # candidates and failed extractions stay eligible for the next run.
        for url in cluster_member_urls(remapped, winners):
            state.mark_seen(url, today)
        state.prune(today)
        state.save()
        crosspost_to_devto(digest, today, settings.site_url, settings.dev_to_api_key)
    else:
        logger.info("DRY_RUN: skipping seen-state update and Dev.to cross-post")

    elapsed = time.monotonic() - start
    logger.info("Done in %.1fs | %s", elapsed, tracker.summary())
    return 0


if __name__ == "__main__":
    sys.exit(run())
