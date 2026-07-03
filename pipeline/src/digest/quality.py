"""Pre-publish quality gate.

The failure alert only fires when the pipeline crashes, so a structurally
valid but hollow digest (empty bullets, one thin story) would publish
silently. This gate turns those into loud failures, and flags style drift
(AI slop vocabulary) as warnings so prompt regressions are visible in logs.
"""

from __future__ import annotations

import logging
import re

from .models import Digest

logger = logging.getLogger(__name__)

MIN_STORIES = 3
MIN_FIELD_CHARS = 40
MIN_HEADLINE_CHARS = 20
MIN_NARRATION_WORDS = 100

# Vocabulary that reads as machine-written. The synthesis prompt bans these;
# hits here mean the model is drifting and the prompt needs attention.
SLOP_PATTERNS = re.compile(
    r"\b("
    r"delve|dive into|unpack|unleash|unlock|supercharge|game.chang\w+|"
    r"revolutioni\w+|groundbreaking|cutting.edge|seamless\w*|"
    r"paradigm|elevate|empower|harness\w*|leverag\w+|"
    r"crucial|pivotal|it'?s worth noting|it'?s important to note|"
    r"at the end of the day|look no further|in the world of|in the realm of"
    r")\b",
    re.IGNORECASE,
)


class QualityGateError(RuntimeError):
    """Raised when a digest is too thin or broken to publish."""


def _story_fields(digest: Digest) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = [("intro", digest.intro)]
    for n, story in enumerate(digest.stories, start=1):
        fields.extend(
            [
                (f"story {n} headline", story.headline),
                (f"story {n} what_happened", story.what_happened),
                (f"story {n} why_it_matters", story.why_it_matters),
                (f"story {n} outlook", story.outlook),
            ]
        )
    return fields


def check_quality(digest: Digest, *, expected_story_count: int | None = None) -> None:
    """Raise QualityGateError for publish-blocking problems; log style warnings."""
    problems: list[str] = []

    if expected_story_count is not None and len(digest.stories) != expected_story_count:
        problems.append(
            f"synthesis returned {len(digest.stories)} stories, expected {expected_story_count}"
        )

    if len(digest.stories) < MIN_STORIES:
        problems.append(f"only {len(digest.stories)} stories (minimum {MIN_STORIES})")

    if len(digest.title.strip()) < MIN_HEADLINE_CHARS:
        problems.append(f"title too short: {digest.title!r}")

    for name, value in _story_fields(digest):
        threshold = MIN_HEADLINE_CHARS if name.endswith("headline") else MIN_FIELD_CHARS
        if len(value.strip()) < threshold:
            problems.append(f"{name} too short ({len(value.strip())} chars)")

    for story in digest.stories:
        if not story.source_urls:
            problems.append(f"story {story.headline!r} has no source URLs")

    if len(digest.narration_script.split()) < MIN_NARRATION_WORDS:
        problems.append(
            f"narration script too short ({len(digest.narration_script.split())} words)"
        )

    if problems:
        raise QualityGateError("Digest failed quality gate: " + "; ".join(problems))

    # Style drift: warn, never block. One slip is tolerable; a pattern in the
    # logs over days means the prompt needs tightening.
    for name, value in [("title", digest.title), *_story_fields(digest)]:
        for match in SLOP_PATTERNS.finditer(value):
            logger.warning("Slop vocabulary in %s: %r", name, match.group(0))
