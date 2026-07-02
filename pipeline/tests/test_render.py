from __future__ import annotations

from datetime import date
from pathlib import Path

from digest.models import Digest
from digest.render import reading_time_minutes, render_markdown, write_post


def test_frontmatter_fields(sample_digest: Digest) -> None:
    md = render_markdown(sample_digest, date(2026, 7, 2))
    frontmatter = md.split("---")[1]
    assert 'title: "The Morning Build' in frontmatter
    assert "date: 2026-07-02" in frontmatter
    assert "tags: [ai, chips]" in frontmatter
    assert "storyCount: 2" in frontmatter
    assert "audio: null" in frontmatter
    assert "https://example.com/acme-chip" in frontmatter


def test_body_structure(sample_digest: Digest) -> None:
    md = render_markdown(sample_digest, date(2026, 7, 2))
    body = md.split("---", 2)[2]
    assert body.count("## ") == 2
    assert body.count("**What happened:**") == 2
    assert body.count("**Why it matters:**") == 2
    assert body.count("**Outlook:**") == 2
    # Source links render with bare domains as text
    assert "[example.com](https://example.com/acme-chip)" in body


def test_reading_time_is_at_least_one_minute(sample_digest: Digest) -> None:
    assert reading_time_minutes(sample_digest) >= 1


def test_write_post_creates_md_and_json(sample_digest: Digest, tmp_path: Path) -> None:
    md_path, json_path = write_post(sample_digest, date(2026, 7, 2), tmp_path)
    assert md_path.name == "2026-07-02.md"
    assert json_path.name == "2026-07-02.json"
    assert md_path.read_text(encoding="utf-8").startswith("---")
    # The JSON must round-trip back into the Digest model (email/audio consumers rely on it).
    assert Digest.model_validate_json(json_path.read_text(encoding="utf-8")) == sample_digest


def test_yaml_special_characters_escaped(sample_digest: Digest) -> None:
    digest = sample_digest.model_copy(
        update={"title": 'He said: "50% \\ off"', "meta_description": "desc"}
    )
    md = render_markdown(digest, date(2026, 7, 2))
    assert 'title: "He said: \\"50% \\\\ off\\""' in md
