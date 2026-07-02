"""Stage B: digest synthesis with gpt-5-mini and structured outputs.

The model fills a Pydantic schema; markdown is rendered deterministically in
Python afterwards. Faithfulness comes from grounding rules + structured output,
not temperature (reasoning models don't support it).
"""

from __future__ import annotations

import logging

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
- source_urls: only URLs given for that story.
- topic_tag: exactly one of: ai, chips, startups, big-tech, dev-tools, policy.
- title: catchy but factual, must include the date in a natural form.
- intro: 1-2 sentences framing the day's theme.
- meta_description: at most 155 characters, compelling, no clickbait.
- narration_script: a smooth spoken-word version of the whole digest, written
  to be read aloud in about two minutes (no headers, no URLs, natural
  transitions between stories).
"""


def build_synthesis_input(
    date_str: str,
    entries: list[FeedEntry],
    clusters: list[StoryCluster],
) -> str:
    """Assemble the user message: date first, then one block per story cluster.

    For clusters with multiple sources, the longest extraction is the primary
    text; the rest contribute headline + URL only (duplicate coverage is not
    worth duplicate tokens).
    """
    blocks = [f"Today's date: {date_str}", f"Number of stories: {len(clusters)}"]
    for n, cluster in enumerate(clusters, start=1):
        members = [entries[i] for i in cluster.entry_indices]
        primary = max(members, key=lambda e: len(e.full_text))
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
    return digest
