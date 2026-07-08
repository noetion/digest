"""Stage B: digest synthesis with gpt-5-mini and structured outputs.

The model fills a Pydantic schema; markdown is rendered deterministically in
Python afterwards. Faithfulness comes from grounding rules + structured output,
not temperature (reasoning models don't support it).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from urllib.parse import urlsplit

from openai import OpenAI

from .config import SYNTHESIS_MODEL
from .costs import CostTracker
from .event_match import cluster_is_coherent
from .models import Digest, FeedEntry, StoryCluster

logger = logging.getLogger(__name__)

# Published bylines mirror synthesis input: 1 primary, up to 2 corroborating (max 3).
MAX_SOURCE_URLS = 3

# First-party vendor/research posts beat news coverage in the same cluster.
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

# Tie-break when two news outlets cover the same event (higher = preferred primary).
_OUTLET_QUALITY: dict[str, int] = {
    "the-decoder.com": 3,
    "arstechnica.com": 3,
    "spectrum.ieee.org": 3,
    "technologyreview.com": 2,
    "wired.com": 2,
    "techcrunch.com": 1,
    "venturebeat.com": 0,
}


def _outlet_quality(url: str) -> int:
    return _OUTLET_QUALITY.get(_domain(url), 1)


def _primary_rank(entry: FeedEntry) -> tuple[int, int]:
    return (len(entry.full_text), _outlet_quality(entry.url))

# Known news aggregators — never first-party even if URL path looks editorial.
_NEWS_OUTLET_DOMAINS = frozenset(
    {
        "venturebeat.com",
        "techcrunch.com",
        "arstechnica.com",
        "theverge.com",
        "wired.com",
        "the-decoder.com",
        "technologyreview.com",
        "theregister.com",
        "ieee.org",
        "spectrum.ieee.org",
    }
)

# Static, byte-identical system prompt -> automatic prefix caching across runs.
# Never interpolate anything dynamic (like the date) into this string.
SYNTHESIS_SYSTEM_PROMPT = """\
You are the editor of "The Morning Build", a daily tech digest for software
engineers and AI practitioners.

You receive today's date and the top stories of the day. Each story has a
primary source text plus optional corroborating headlines. Write the daily
digest, filling the provided schema exactly.

When the primary source is an official vendor research or product post, anchor
the headline and what_happened on that source, not secondary news coverage.

Editorial rules (non-negotiable):
- Voice: sharp, technical, zero fluff. Written for engineers, not general
  consumers. Numbers and concrete details over adjectives.
- Ground EVERY statement strictly in the provided source text. If the sources
  do not say it, do not write it. Never speculate beyond what a source
  explicitly frames as expectation or plan.
- No sensationalism. No exclamation marks.
- headline: written like a searchable news headline (specific, active voice).
  Write license names with a space (Apache 2.0, MIT), never Apache: 2.0. Write
  memory footprints as under 300GB, not sub-300GB or sub: 300GB.
- what_happened: the facts, 1-2 tight sentences.
- why_it_matters: the practical/technical impact for engineers, 1-2 sentences.
- outlook: one sentence on what to look for next in this story: a named date,
  fiscal period, ship window, trial window, filing, public milestone, hiring
  signal, benchmark result, or follow-on move the source sets up. Write for a
  general software-engineering reader, not a niche role or employer context.
  Core rules (always apply):
  - Name a concrete forward signal grounded in the source. The reader should
    know what datapoint or milestone comes next without rereading the story.
  - Look-ahead, not homework: state what is ahead in the news, not instructions
    for marketing, legal, partnerships, or org-specific audits.
  - Ground in sources only. No vague industry punditry.
  How to make it useful (not generic or preachy):
  - Prefer milestones anyone following the story can watch: fiscal-year updates,
    remaining layoff tranches, Frontier hiring moves, OpenRouter trial windows,
    conference sessions, regulatory deadlines, third-party benchmark releases.
  - Use a number, product name, or date from the story when the source provides
    one. Specificity is what makes it helpful.
  - Do not assume the reader works in a special function (Xbox partner manager,
    ad buyer, compliance lead). Do not open with "If your roadmap…" or "Have
    marketing and legal…"
  Good: "Fiscal-year 2027 updates will show the remaining expected cuts and how
  Microsoft's Frontier Company investments translate into staffing and product
  changes."
  Good: "The two-week OpenRouter Hy3 window is the first public check on whether
  Tencent's reliability and serving-cost claims hold outside internal tests."
  Good: "Artificial Analysis and vendor coding benchmarks are the next public
  check on whether Hy3's agent and long-context claims hold outside Tencent's
  internal tests."
  Good: "July 2026 quota renewals will show whether Zhipu keeps ZCode's elevated
  token limits or rolls them back after the launch window."
  Good: "Expedia's VB Transform session on July 14 at 11:10 a.m. PT should spell
  out which Agentic Release tollgates are already automated in the SDLC."
  Good: "The FCA-commissioned report due this week starts a three- to six-month
  review window that could redraw which consumer AI finance apps sit in scope."
  Good: "Cloudflare's September 15, 2026 ad-page defaults will show how many
  training and agent crawlers get reclassified under BotBase."
  Good: "The next commits on the published Command and Conquer iOS repo should
  show whether the logged iPad memory crashes are fixed."
  Bad: "Watch for independent benchmark updates such as Artificial Analysis."
  Bad: "Track subscriber quota expirations through July 2026 to see whether Zhipu
  keeps the elevated quotas."
  Bad: "Monitor Cloudflare's BotBase rollout and the September 15 enforcement
  date to measure traffic pattern changes."
  Bad: "If your product or partnership roadmap depends on Xbox teams or studio
  relationships, audit current points of contact and contracts now."
  Bad: "Have marketing and legal review your next AI-assisted UX or ad and run a
  cross-platform sentiment test before broad ad buys."
  Bad: "Watch whether vendors blur the line with infrastructure providers." (vague)
  Bad: "Track comparative performance versus Claude Code on real workflows." (empty)
  Bad: "Expect other large operators to publish similar guardrails." (generic)
  Bad: "Follow commits and the published engineering log on the project's GitHub
  repo for the next stability fixes." (instructional)
  Bad: "...Artificial Analysis remain the next external verification to watch."
  (passive tail)
  Start outlook with the milestone itself (date, report, deadline, benchmark name,
  repo update, quota renewal), not Watch for, Track, Monitor, or Follow.
- topic_tag: exactly one of: ai, chips, startups, big-tech, dev-tools, policy.
- title: must name the day's theme, not just the date. Format: "The Morning
  Build for <Month D, YYYY>: <theme that makes an engineer keep reading>".
  The theme appears in RSS, search, and shared links. Your job is to earn the
  click in one line: specific enough to trust, lively enough to care, never
  breathless or tabloid.
  Core rules (always apply):
  - Plain English a busy engineer scans in two seconds: company names, numbers,
    licenses, or tension. No jargon slugs or abstract noun stacks.
  - At least one recognizable proper noun from today's stories is required; two
    or more is better when they fit.
  - Do not use coined compound phrases ("model-agent split") or vague stacks
    ("agent coding pushes"), or comma-lists of abstract jargon.
  How to make it engaging (not dramatic):
  - Lead with what CHANGED today: a ship, a cut, a license, a policy flip, a
    new product name. Static labels ("AI updates") bore; verbs and numbers hook.
  - Create quiet tension: contrast, stakes, or a question the stories answer.
    Good tension uses facts ("models vs. agents", "4,800 roles", "Apache 2.0"),
    not hype words ("explosive", "massive", "unprecedented", "shocking").
  - Name real companies or products readers recognize. Proper nouns carry weight.
  - Use active, concrete phrasing. Write like a sharp morning briefing, not a
    filing index or a LinkedIn thought-leadership post.
  - Three beats max after the colon: lead hook, second story anchor, optional
    third. Each beat should be scannable (roughly 3-6 words).
  - Reflect the stories actually in the digest. If a major platform or layoff
    story is included (Vercel, Microsoft, Expedia, Cloudflare), name it in the
    title beats; do not list only model vendors when platform news is present.
  Good: "The Morning Build for July 2, 2026: Custom Silicon, Enterprise AI,
  and the Power Bill" (concrete, slightly unexpected third beat).
  Good: "The Morning Build for July 6, 2026: Vercel Splits Models from Agents,
  Hy3 Goes Apache, Microsoft Cuts 4,800" (verbs, names, a number).
  Good: "The Morning Build for March 12, 2026: OpenAI Codex Tier Changes,
  EU Export Rules, and the Layoffs Behind AI Bets" (stakes without screaming).
  Bad: "The Morning Build, July 02, 2026" (date only, no reason to open).
  Bad: "The Morning Build for July 6, 2026: model-agent split, open-weight Hy3,
  and agent coding pushes" (coined jargon, no hook, reads like a slug).
  Bad: "The Morning Build for July 6, 2026: The AI Revolution Heats Up as
  Tech Giants Battle for Agent Supremacy!!!" (hype, no facts, sensational).
  Bad: "The Morning Build for July 6, 2026: Five Things You Missed While
  You Slept" (clickbait, no substance).
  Bad: "The Morning Build for July 6, 2026: Tencent's Apache Hy3, Zhipu's
  ZCode, and Microsoft's 4,800 Cuts" when the digest also includes Google
  opt-out or Expedia (title omits major stories that appear in the body).
  No exclamation marks. No "you won't believe", "everything changed",
  "game-changing day", or empty superlatives.
- intro: 1-2 sentences stating the day's theme and the thread connecting ALL
  stories in this digest. NEVER a list of the headlines; the reader is about
  to scroll through those. Every story must appear in the intro, either by
  name or by a clear grouped phrase (e.g. "open-weight models from Tencent
  and Zhipu; Microsoft's cuts; Google's training opt-out; and Expedia's
  agent-release gates"). NEVER use an explicit count ("three platform moves",
  "five updates") unless that number equals the exact story count you were
  given. Plain English; no academic framing ("bifurcating along two
  axes", "along two vectors", "paradigm shift"). Good: "Big Tech is verticalizing
  AI: custom chips, in-house deployment arms, and the electricity bills to
  match." Bad: "Three platform moves today matter for engineers..." when the
  digest has five stories including Google policy and FCA review. Bad: "Five
  updates: a chip deal, a new app..." (headline list). Bad: "Open-weight models
  and agent platforms are bifurcating along two axes."
- meta_description: at most 155 characters, compelling, no clickbait. Lead with
  the strongest hook (company name, number, or product), not a vague summary.
  Use the same engaged-but-sober voice as the title so someone scanning RSS
  wants the next sentence.
- narration_script: a smooth spoken-word version of the whole digest, written
  to be read aloud in about two minutes (no headers, no URLs, natural
  transitions between stories). State forward milestones plainly; do not tell
  listeners to watch or follow a repo.

Style rules (equally non-negotiable). Write like a seasoned human newsletter
editor, never like an AI assistant:
- NEVER use em dashes (the — character) or double hyphens as dash substitutes.
  Restructure the sentence, or use a comma, colon, or period instead. En dashes
  (the – character) are fine in numeric ranges and compounds (e.g. GLM-5.2–based).
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


def _is_first_party(entry: FeedEntry) -> bool:
    """True for vendor research posts and official company blogs."""
    domain = _domain(entry.url)
    if domain in _NEWS_OUTLET_DOMAINS:
        return False
    if domain in _FIRST_PARTY_DOMAINS:
        return True
    return any(domain.endswith(f".{suffix}") for suffix in _FIRST_PARTY_DOMAINS)


def _dominant_domain(entries: list[FeedEntry], clusters: list[StoryCluster]) -> str | None:
    """The domain that would supply the primary text for more than one story."""
    counts = Counter(
        _domain(_pick_primary([entries[i] for i in c.entry_indices], None).url)
        for c in clusters
    )
    domain, n = counts.most_common(1)[0]
    return domain if n > 1 else None


def _pick_primary(members: list[FeedEntry], dominant: str | None) -> FeedEntry:
    """Prefer official first-party posts; otherwise longest extraction wins.

    When one outlet dominates the digest, near-equal alternates (>= 70% text
    length) from other outlets break ties for source diversity.
    """
    first_party = [m for m in members if _is_first_party(m)]
    pool = first_party if first_party else members

    longest = max(pool, key=_primary_rank)
    if first_party or dominant is None or _domain(longest.url) != dominant:
        return longest
    threshold = 0.7 * len(longest.full_text)
    alternates = [
        m
        for m in pool
        if _domain(m.url) != dominant and len(m.full_text) >= threshold
    ]
    if alternates:
        return max(alternates, key=_primary_rank)
    return longest


def _story_sources(
    members: list[FeedEntry],
    dominant: str | None,
) -> tuple[FeedEntry, list[FeedEntry]]:
    """Primary article plus up to two corroborating outlets fed to synthesis."""
    primary = _pick_primary(members, dominant)
    others = [m for m in members if m is not primary]
    others.sort(
        key=lambda m: (
            _domain(m.url) == _domain(primary.url),
            -len(m.full_text),
        ),
    )
    return primary, others[: MAX_SOURCE_URLS - 1]


def source_urls_for_story(members: list[FeedEntry], dominant: str | None) -> list[str]:
    """URLs for the primary and corroborating articles synthesis actually sees."""
    primary, corroborating = _story_sources(members, dominant)
    seen: set[str] = set()
    ordered: list[str] = []
    for url in [primary.url, *(c.url for c in corroborating)]:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


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
        primary, corroborating = _story_sources(members, dominant)
        block = [
            f"--- STORY {n} ---",
            f"Editor's note: {cluster.reason}",
            f"Primary source: {primary.title} ({primary.source})",
            f"URL: {primary.url}",
        ]
        if corroborating:
            block.append("Corroborating coverage:")
            block.extend(f"- {m.title} ({m.source}) {m.url}" for m in corroborating)
        block.append("")
        block.append(primary.full_text)
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


# Glued hyphens from em-dash scrub or model output (not valid compounds).
_LICENSE_NAMES = r"Apache|MIT|BSD|GPL|LGPL|AGPL|Mozilla"
_UNDER_BEFORE_DIGIT = re.compile(
    r"\b(sub|under|approx|about)(?:\u2014|-|:)(\d)",
    re.IGNORECASE,
)
_LICENSE_COLON = re.compile(
    rf"\b({_LICENSE_NAMES}): (\d)",
    re.IGNORECASE,
)
_GLUE_HYPHEN_DIGIT = re.compile(r"(?<![.\d])([a-z]{3,})-(\d)")
_GLUE_HYPHEN_QUALIFIER = re.compile(
    r"\b(\w+)-(recommended|required|sometimes|practices|optional)\b",
    re.IGNORECASE,
)


def _scrub_em_dash_before_digit(text: str) -> str:
    text = _UNDER_BEFORE_DIGIT.sub(r"under \2", text)
    text = re.sub(
        rf"\b({_LICENSE_NAMES})\u2014(\d+\.?\d*)",
        r"\1 \2",
        text,
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match[str]) -> str:
        word = match.group(1)
        digit = match.group(2)
        lower = word.lower()
        if lower in {"sub", "under", "approx", "about"}:
            return f"under {digit}"
        if re.fullmatch(_LICENSE_NAMES, word, re.IGNORECASE):
            return f"{word} {digit}"
        return f"{word}: {digit}"

    return re.sub(r"(\w)\u2014(\d)", repl, text)


def _fix_scrub_artifacts(text: str) -> str:
    """Repair colon glitches from em-dash scrub (licenses, memory shorthand)."""
    text = _LICENSE_COLON.sub(r"\1 \2", text)
    text = _UNDER_BEFORE_DIGIT.sub(r"under \2", text)
    return text


def _fix_glued_hyphens(text: str) -> str:
    """Repair word-digit and word-qualifier hyphens that are not real compounds."""
    text = _UNDER_BEFORE_DIGIT.sub(r"under \2", text)
    text = _GLUE_HYPHEN_DIGIT.sub(r"\1: \2", text)
    text = _GLUE_HYPHEN_QUALIFIER.sub(r"\1, \2", text)
    return _fix_scrub_artifacts(text)


def _scrub_text(text: str) -> str:
    """Remove em dashes the model slips through despite the prompt.

    Spaced em dashes become comma pauses. Unspaced em dashes before digits become
    under/colon/space depending on context. En dashes are left intact.
    """
    text = text.replace(" \u2014 ", ", ").replace("\u2014 ", ", ").replace(" \u2014", ", ")
    text = _scrub_em_dash_before_digit(text)
    text = text.replace("\u2014", ", ")
    return _fix_glued_hyphens(text)


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
    dominant = _dominant_domain(entries, clusters)
    for story, cluster in zip(digest.stories, clusters, strict=True):
        members = [entries[i] for i in cluster.entry_indices]
        if not cluster_is_coherent(cluster, entries):
            headline = members[0].title if members else "?"
            raise ValueError(
                f"incoherent source cluster for {headline!r}: "
                "members do not describe the same event"
            )
        story.source_urls = source_urls_for_story(members, dominant)
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
