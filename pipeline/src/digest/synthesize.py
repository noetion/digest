"""Stage B: digest synthesis with gpt-5-mini and structured outputs.

The model fills a Pydantic schema; markdown is rendered deterministically in
Python afterwards. Faithfulness comes from grounding rules + structured output,
not temperature (reasoning models don't support it).
"""

from __future__ import annotations

import logging
from collections import Counter
from urllib.parse import urlsplit

from openai import OpenAI

from .config import SYNTHESIS_MODEL
from .costs import CostTracker
from .models import Digest, FeedEntry, StoryCluster

logger = logging.getLogger(__name__)

# Static, byte-identical system prompt -> automatic prefix caching across runs.
# Never interpolate anything dynamic (like the date) into this string.
SYNTHESIS_SYSTEM_PROMPT = """\
You are the editor of "The Morning Build", a daily tech digest for software
engineers and AI practitioners.

You receive today's date and the top stories of the day. Each story has a
primary source text plus optional corroborating headlines. Write the daily
digest, filling the provided schema exactly.

Editorial rules (non-negotiable):
- Voice: sharp, technical, zero fluff. Written for engineers, not general
  consumers. Numbers and concrete details over adjectives.
- Ground EVERY statement strictly in the provided source text. If the sources
  do not say it, do not write it. Never speculate beyond what a source
  explicitly frames as expectation or plan.
- No sensationalism. No exclamation marks.
- headline: written like a searchable news headline (specific, active voice).
- what_happened: the facts, 1-2 tight sentences.
- why_it_matters: the practical/technical impact for engineers, 1-2 sentences.
- outlook: context or what to watch next, 1 sentence.
- topic_tag: exactly one of: ai, chips, startups, big-tech, dev-tools, policy.
- title: must name the day's theme, not just the date. Format: "The Morning
  Build for <Month D, YYYY>: <the day's theme in a few concrete words>".
  Good: "The Morning Build for July 2, 2026: Custom Silicon, Enterprise AI,
  and the Power Bill". Bad: "The Morning Build, July 02, 2026". The theme
  words are what people see in search results and shared links, so make them
  specific to today's stories.
- intro: 1-2 sentences stating the day's theme, the thread connecting the
  stories. NEVER a list of the headlines; the reader is about to scroll
  through those. Good: "Big Tech is verticalizing AI: custom chips, in-house
  deployment arms, and the electricity bills to match." Bad: "Five updates: a
  chip deal, a new app, a $2.5B unit, an equity proposal, and energy news."
- meta_description: at most 155 characters, compelling, no clickbait.
- narration_script: a smooth spoken-word version of the whole digest, written
  to be read aloud in about two minutes (no headers, no URLs, natural
  transitions between stories).

Style rules (equally non-negotiable). Write like a seasoned human newsletter
editor, never like an AI assistant:
- NEVER use em dashes (the — character) or double hyphens. Restructure the
  sentence, or use a comma, colon, or period instead.
- Never use these words or their variants: delve, dive into, unpack, unleash,
  unlock, supercharge, game-changer, game-changing, revolutionize,
  revolutionary, groundbreaking, cutting-edge, seamless, seamlessly, robust,
  landscape, ecosystem-wide, paradigm, elevate, empower, harness, leverage
  (as a verb), navigate (figuratively), crucial, pivotal, "in the world of",
  "in the realm of", "it's worth noting", "it's important to note",
  "at the end of the day", "look no further".
- No formulaic openers ("In a move that...", "In today's fast-paced...").
  Start with the concrete fact.
- Vary sentence rhythm. Mix short declarative sentences with longer ones.
  Never write three sentences in a row with the same structure.
- No triads for their own sake ("faster, cheaper, and more reliable" style
  lists in every sentence reads as machine-written).
- No hedging filler ("arguably", "essentially", "generally speaking") and no
  empty summarizing ("Overall, this is a significant development").
- Plain verbs beat fancy ones: "use" not "utilize", "start" not "commence",
  "show" not "showcase".
"""


def _domain(url: str) -> str:
    return urlsplit(url).netloc.removeprefix("www.")


def _dominant_domain(entries: list[FeedEntry], clusters: list[StoryCluster]) -> str | None:
    """The domain that would supply the primary text for more than one story."""
    counts = Counter(
        _domain(max((entries[i] for i in c.entry_indices), key=lambda e: len(e.full_text)).url)
        for c in clusters
    )
    domain, n = counts.most_common(1)[0]
    return domain if n > 1 else None


def _pick_primary(members: list[FeedEntry], dominant: str | None) -> FeedEntry:
    """Longest extraction wins, unless a near-equal alternative (>= 70% of the
    longest text) comes from a less-represented outlet. One outlet dominating
    every byline reads as a single-source digest even when the stories are
    right, so ties break toward source diversity, never at the cost of
    substance."""
    longest = max(members, key=lambda e: len(e.full_text))
    if dominant is None or _domain(longest.url) != dominant:
        return longest
    threshold = 0.7 * len(longest.full_text)
    alternates = [
        m
        for m in members
        if _domain(m.url) != dominant and len(m.full_text) >= threshold
    ]
    if alternates:
        return max(alternates, key=lambda e: len(e.full_text))
    return longest


def build_synthesis_input(
    date_str: str,
    entries: list[FeedEntry],
    clusters: list[StoryCluster],
) -> str:
    """Assemble the user message: date first, then one block per story cluster.

    For clusters with multiple sources, the longest extraction is the primary
    text (with a diversity tiebreak, see _pick_primary); the rest contribute
    headline + URL only (duplicate coverage is not worth duplicate tokens).
    """
    dominant = _dominant_domain(entries, clusters)
    blocks = [f"Today's date: {date_str}", f"Number of stories: {len(clusters)}"]
    for n, cluster in enumerate(clusters, start=1):
        members = [entries[i] for i in cluster.entry_indices]
        primary = _pick_primary(members, dominant)
        block = [
            f"--- STORY {n} ---",
            f"Editor's note: {cluster.reason}",
            f"Primary source: {primary.title} ({primary.source})",
            f"URL: {primary.url}",
        ]
        corroborating = [m for m in members if m is not primary]
        if corroborating:
            block.append("Corroborating coverage:")
            block.extend(f"- {m.title} ({m.source}) {m.url}" for m in corroborating)
        block.append("")
        block.append(primary.full_text)
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def _scrub_text(text: str) -> str:
    """Remove em dashes the model slips through despite the prompt.

    A spaced em dash becomes a comma pause; an unspaced one (rare) becomes a
    plain hyphen so compound words survive.
    """
    text = text.replace(" \u2014 ", ", ").replace("\u2014 ", ", ").replace(" \u2014", ", ")
    return text.replace("\u2014", "-")


def scrub_digest(digest: Digest) -> Digest:
    """Deterministic post-pass: no em dashes in any published field."""
    digest.title = _scrub_text(digest.title)
    digest.intro = _scrub_text(digest.intro)
    digest.meta_description = _scrub_text(digest.meta_description)
    digest.narration_script = _scrub_text(digest.narration_script)
    for story in digest.stories:
        story.headline = _scrub_text(story.headline)
        story.what_happened = _scrub_text(story.what_happened)
        story.why_it_matters = _scrub_text(story.why_it_matters)
        story.outlook = _scrub_text(story.outlook)
    return digest


def attach_cluster_sources(
    digest: Digest,
    entries: list[FeedEntry],
    clusters: list[StoryCluster],
) -> Digest:
    """Assign source URLs from triage clusters. The LLM must not choose sources."""
    if len(digest.stories) != len(clusters):
        raise ValueError(
            f"synthesis returned {len(digest.stories)} stories for {len(clusters)} clusters"
        )
    for story, cluster in zip(digest.stories, clusters, strict=True):
        story.source_urls = sorted({entries[i].url for i in cluster.entry_indices})
    return digest


def synthesize(
    client: OpenAI,
    date_str: str,
    entries: list[FeedEntry],
    clusters: list[StoryCluster],
    tracker: CostTracker,
) -> Digest:
    tracker.check_budget()
    response = client.responses.parse(
        model=SYNTHESIS_MODEL,
        reasoning={"effort": "low"},
        max_output_tokens=4000,
        input=[
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": build_synthesis_input(date_str, entries, clusters)},
        ],
        text_format=Digest,
    )
    tracker.record(SYNTHESIS_MODEL, response.usage)

    digest = response.output_parsed
    if digest is None:
        raise RuntimeError("Synthesis returned no parsed output")
    logger.info("Synthesized digest with %d stories", len(digest.stories))
    return scrub_digest(digest)
