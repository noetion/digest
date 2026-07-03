"""Pipeline orchestrator: python -m digest.main

Stages: fetch feeds -> dedup -> triage (cheap) -> extract full text (winners
only) -> synthesize -> render markdown+JSON -> mark seen -> optional Dev.to
cross-post. CI commits the rendered files, which triggers the site deploy.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import UTC, datetime

from openai import OpenAI

from .config import CONTENT_DIR, DRY_RUN_OUT_DIR, SEEN_STATE_PATH, load_settings
from .costs import CostTracker
from .dedupe import SeenState, filter_unseen
from .extract import enrich_with_full_text
from .feeds import fetch_all_feeds
from .models import FeedEntry, StoryCluster
from .publish import crosspost_to_devto
from .quality import check_quality
from .render import write_post
from .synthesize import synthesize
from .triage import triage

logger = logging.getLogger(__name__)


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


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    start = time.monotonic()
    settings = load_settings()
    today = datetime.now(tz=UTC).date()
    content_dir = DRY_RUN_OUT_DIR if settings.dry_run else CONTENT_DIR

    # Idempotency guard: exit cleanly if today's digest already exists.
    if (CONTENT_DIR / f"{today.isoformat()}.md").exists() and not settings.dry_run:
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
        logger.warning("Triage selected no stories; skipping digest.")
        return 0

    # --- Full-text extraction, winners only ---
    winner_indices = sorted({i for c in clusters for i in c.entry_indices})
    winners = enrich_with_full_text(
        [candidates[i] for i in winner_indices], settings.max_article_words
    )
    remapped = remap_clusters(clusters, candidates, winners)
    if not remapped:
        logger.error("All winning articles failed extraction; aborting.")
        return 1
    logger.info("Extracted full text for %d winning articles", len(winners))

    # --- LLM stage B: synthesis ---
    date_str = today.strftime("%A, %B %d, %Y")
    digest = synthesize(client, date_str, winners, remapped, tracker)
    check_quality(digest)

    # --- Render + state ---
    md_path, json_path = write_post(digest, today, content_dir)
    logger.info("Wrote %s and %s", md_path, json_path)

    if not settings.dry_run:
        # Mark every candidate seen (not just winners): rejected stories were
        # considered and shouldn't be re-triaged tomorrow.
        for entry in candidates:
            state.mark_seen(entry.url, today)
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
