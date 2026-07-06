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

_EM_DASH = re.compile("\u2014")

ABS_MIN_STORIES = 2  # never publish a one-story digest
MIN_STORIES = 3  # target; thin news days may publish fewer
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
    r"at the end of the day|look no further|in the world of|in the realm of|"
    r"bifurcat\w*|along two axes"
    r")\b",
    re.IGNORECASE,
)

# Vague outlook hedges the synthesis prompt bans; warn on outlook fields only.
OUTLOOK_FILLER_PATTERNS = re.compile(
    r"(?i)^("
    r"watch\s+for|"
    r"watch\s+whether|"
    r"watch\s+if|"
    r"watch\s+how\s+(?:the\s+)?industry|"
    r"track\s+|"
    r"monitor\s+|"
    r"follow\s+|"
    r"expect\s+other|"
    r"it\s+remains\s+to\s+be\s+seen|"
    r"only\s+time\s+will\s+tell|"
    r"independent\s+(?:benchmark\s+)?verification\s+will\s+be\s+required|"
    r"this\s+could\s+change\s+how|"
    r"this\s+is\s+(?:a\s+)?significant\s+development"
    r")"
)

OUTLOOK_TAIL_FILLER = re.compile(
    r"(?i)\b(?:verification to watch|remain the next external verification to watch)\b"
)

_INTRO_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}
_INTRO_EXPLICIT_COUNT = re.compile(
    r"(?i)\b(one|two|three|four|five|six)\s+(?:\w+\s+){0,4}"
    r"(?:moves|stories|updates|headlines|things|developments)\b"
)

# Role-specific instructions mis-framed as outlook; warn only.
OUTLOOK_INSTRUCTION_PATTERNS = re.compile(
    r"(?i)^("
    r"have\s+(?:marketing|legal|your\s+team)|"
    r"if\s+your\s+(?:product|partnership|roadmap)|"
    r"map\s+.+\s+to\s+your\s+(?:ci/?cd|release\s+checklist)|"
    r"audit\s+(?:current\s+)?(?:points\s+of\s+contact|contracts)|"
    r"follow\s+commits"
    r")"
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

    required = MIN_STORIES
    if expected_story_count is not None and expected_story_count < MIN_STORIES:
        required = ABS_MIN_STORIES
    if len(digest.stories) < required:
        problems.append(f"only {len(digest.stories)} stories (minimum {required})")
    elif len(digest.stories) < MIN_STORIES:
        logger.warning(
            "Thin digest: %d stories (target %d)", len(digest.stories), MIN_STORIES
        )

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

    for name, value in [("title", digest.title), *_story_fields(digest)]:
        if _EM_DASH.search(value):
            problems.append(f"{name} contains em dash after scrub")

    if problems:
        raise QualityGateError("Digest failed quality gate: " + "; ".join(problems))

    # Style drift: warn, never block. One slip is tolerable; a pattern in the
    # logs over days means the prompt needs tightening.
    for name, value in [("title", digest.title), *_story_fields(digest)]:
        for match in SLOP_PATTERNS.finditer(value):
            logger.warning("Slop vocabulary in %s: %r", name, match.group(0))

    for n, story in enumerate(digest.stories, start=1):
        if OUTLOOK_FILLER_PATTERNS.search(story.outlook.strip()):
            logger.warning(
                "Generic outlook filler in story %d outlook: %r",
                n,
                story.outlook[:80],
            )
        if OUTLOOK_INSTRUCTION_PATTERNS.search(story.outlook.strip()):
            logger.warning(
                "Outlook reads like instructions in story %d: %r",
                n,
                story.outlook[:80],
            )
        if OUTLOOK_TAIL_FILLER.search(story.outlook):
            logger.warning(
                "Passive outlook tail in story %d: %r",
                n,
                story.outlook[:80],
            )

    intro_count = _INTRO_EXPLICIT_COUNT.search(digest.intro)
    if intro_count:
        stated = _INTRO_COUNT_WORDS.get(intro_count.group(1).lower())
        if stated is not None and stated != len(digest.stories):
            logger.warning(
                "Intro count mismatch (%d claimed, %d stories): %r",
                stated,
                len(digest.stories),
                digest.intro[:80],
            )
