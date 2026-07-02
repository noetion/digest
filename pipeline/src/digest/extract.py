"""Stage 2b: full-text extraction (trafilatura) and token-efficiency trimming.

Trimming before any LLM call is the single biggest cost lever in the pipeline.
"""

from __future__ import annotations

import logging
import re

import httpx
import trafilatura
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import USER_AGENT
from .models import FeedEntry

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)

_SENTENCE_END = re.compile(r"[.!?…]['\")\]]?\s*$")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=15), reraise=True)
def _download_html(url: str) -> str:
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text


def _strip_boilerplate_tail(paragraphs: list[str]) -> list[str]:
    """Drop trailing short, punctuation-less paragraphs (related links, signups, bios)."""
    while paragraphs:
        tail = paragraphs[-1].strip()
        if len(tail.split()) < 20 and not _SENTENCE_END.search(tail):
            paragraphs.pop()
        else:
            break
    return paragraphs


def trim_text(text: str, max_words: int) -> str:
    """Trim to max_words at a paragraph boundary, then strip boilerplate tails."""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    paragraphs = [p for p in text.split("\n\n") if p.strip()]

    kept: list[str] = []
    count = 0
    for paragraph in paragraphs:
        words = len(paragraph.split())
        if kept and count + words > max_words:
            break
        kept.append(paragraph)
        count += words

    kept = _strip_boilerplate_tail(kept)
    return "\n\n".join(kept).strip()


def extract_article(url: str, max_words: int) -> str:
    """Download and extract clean, trimmed markdown for one article."""
    html = _download_html(url)
    text = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=False,
        include_images=False,
        include_comments=False,
    )
    if not text:
        return ""
    return trim_text(text, max_words)


def enrich_with_full_text(entries: list[FeedEntry], max_words: int) -> list[FeedEntry]:
    """Populate full_text on each entry; drop entries whose extraction fails/comes back empty."""
    enriched: list[FeedEntry] = []
    for entry in entries:
        try:
            text = extract_article(entry.url, max_words)
        except Exception:
            logger.warning("Extraction failed for %s, skipping", entry.url, exc_info=True)
            continue
        if not text:
            logger.warning("Empty extraction for %s, skipping", entry.url)
            continue
        enriched.append(entry.model_copy(update={"full_text": text}))
    return enriched
