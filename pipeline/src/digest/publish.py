"""Optional Dev.to cross-post.

The primary publish mechanism is simply committing the rendered post to the
repo (done by CI); the site host auto-deploys on push. Dev.to is bonus reach,
and canonical_url always points at our site so it keeps the SEO credit.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import Digest
from .render import render_body

logger = logging.getLogger(__name__)

DEV_TO_ARTICLES_URL = "https://dev.to/api/articles"
DEV_TO_TAGS = ["ai", "news", "programming", "technology"]


def canonical_digest_url(site_url: str, day: date) -> str:
    return f"{site_url.rstrip('/')}/digest/{day.isoformat()}/"


def build_devto_payload(digest: Digest, day: date, site_url: str) -> dict[str, Any]:
    canonical = canonical_digest_url(site_url, day)
    body = (
        f"{render_body(digest)}\n\n---\n\n"
        f"*Originally published at [The Morning Build]({canonical}).*\n"
    )
    return {
        "article": {
            "title": digest.title,
            "body_markdown": body,
            "published": True,
            "tags": DEV_TO_TAGS,
            "canonical_url": canonical,
        }
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=30), reraise=True)
def _post(payload: dict[str, Any], api_key: str) -> httpx.Response:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            DEV_TO_ARTICLES_URL,
            json=payload,
            headers={"api-key": api_key, "Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response


def crosspost_to_devto(digest: Digest, day: date, site_url: str, api_key: str) -> str | None:
    """Publish to Dev.to; returns the article URL, or None if skipped/failed.

    A cross-post failure is never fatal: the site publish already succeeded.
    """
    if not api_key:
        logger.warning("DEV_TO_API_KEY not set; skipping Dev.to cross-post")
        return None
    try:
        response = _post(build_devto_payload(digest, day, site_url), api_key)
        url = response.json().get("url")
        logger.info("Cross-posted to Dev.to: %s", url)
        return str(url) if url else None
    except Exception:
        logger.warning("Dev.to cross-post failed (non-fatal)", exc_info=True)
        return None
