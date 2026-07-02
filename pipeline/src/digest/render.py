"""Render the canonical Digest JSON into the site's markdown post format."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import Digest

WORDS_PER_MINUTE = 220


def reading_time_minutes(digest: Digest) -> int:
    words = len(digest.intro.split())
    for story in digest.stories:
        words += len(
            f"{story.headline} {story.what_happened} {story.why_it_matters} {story.outlook}".split()
        )
    return max(1, round(words / WORDS_PER_MINUTE))


def _yaml_escape(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_frontmatter(digest: Digest, day: date) -> str:
    tags = sorted({story.topic_tag for story in digest.stories})
    sources = sorted({url for story in digest.stories for url in story.source_urls})
    lines = [
        "---",
        f"title: {_yaml_escape(digest.title)}",
        f"date: {day.isoformat()}",
        f"description: {_yaml_escape(digest.meta_description)}",
        f"tags: [{', '.join(tags)}]",
        f"storyCount: {len(digest.stories)}",
        f"readingTimeMinutes: {reading_time_minutes(digest)}",
        "audio: null",  # reserved: future TTS mp3 URL
        "sources:",
        *[f"  - {_yaml_escape(url)}" for url in sources],
        "---",
    ]
    return "\n".join(lines)


def render_body(digest: Digest) -> str:
    parts = [digest.intro, ""]
    for story in digest.stories:
        source_links = " · ".join(
            f"[{_domain(url)}]({url})" for url in story.source_urls
        )
        parts.extend(
            [
                f"## {story.headline}",
                "",
                f"- **What happened:** {story.what_happened}",
                f"- **Why it matters:** {story.why_it_matters}",
                f"- **Outlook:** {story.outlook}",
                "",
                f"<small>Sources: {source_links}</small>",
                "",
            ]
        )
    return "\n".join(parts).strip() + "\n"


def _domain(url: str) -> str:
    from urllib.parse import urlsplit

    host = urlsplit(url).netloc
    return host.removeprefix("www.")


def render_markdown(digest: Digest, day: date) -> str:
    return f"{render_frontmatter(digest, day)}\n\n{render_body(digest)}"


def write_post(digest: Digest, day: date, content_dir: Path) -> tuple[Path, Path]:
    """Write both the markdown post and the canonical JSON artifact.

    The JSON is what future email and audio renderers will consume.
    """
    content_dir.mkdir(parents=True, exist_ok=True)
    md_path = content_dir / f"{day.isoformat()}.md"
    json_path = content_dir / f"{day.isoformat()}.json"
    md_path.write_text(render_markdown(digest, day), encoding="utf-8", newline="\n")
    json_path.write_text(
        digest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return md_path, json_path
