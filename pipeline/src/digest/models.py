"""Shared data models for the pipeline stages."""

from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from pydantic import BaseModel, Field

_HTML_TAG = re.compile(r"<[^>]+>")


class FeedEntry(BaseModel):
    """A candidate article discovered in an RSS feed."""

    title: str
    url: str
    source: str
    topic: str
    published: datetime | None = None
    summary: str = ""
    full_text: str = ""

    def preview(self, words: int = 80) -> str:
        """Headline-stage preview used by triage (never the full text)."""
        base = self.full_text or self.summary
        text = unescape(_HTML_TAG.sub(" ", base))
        text = " ".join(text.split())
        if not self.full_text and len(text.split()) < 10:
            # HN and similar feeds often ship link-only summaries; triage must
            # rely on the headline rather than treating the entry as noise.
            return "(No useful RSS preview — score from headline and source.)"
        return " ".join(text.split()[:words])


class StoryCluster(BaseModel):
    """A group of entries covering the same underlying story (triage output)."""

    entry_indices: list[int] = Field(description="Indices into the candidate list")
    ai_relevant: bool = Field(
        description="True only if the story materially affects the AI ecosystem"
    )
    significance: int = Field(ge=1, le=10, description="Significance to engineers, 1-10")
    reason: str = Field(description="One line on why this story matters")


class TriageResult(BaseModel):
    clusters: list[StoryCluster]


class Story(BaseModel):
    """One story in the final digest (synthesis output)."""

    headline: str = Field(description="H2-ready, written like a searchable news headline")
    what_happened: str = Field(description="Bullet 1: the facts")
    why_it_matters: str = Field(description="Bullet 2: technical impact for engineers")
    outlook: str = Field(description="Bullet 3: context / what to watch next")
    source_urls: list[str] = Field(description="Every claim must be traceable to these")
    topic_tag: str = Field(description="One of: ai, chips, startups, big-tech, dev-tools, policy")


class Digest(BaseModel):
    """The canonical structured artifact. Markdown, email, and future audio all
    render from this JSON."""

    title: str = Field(description="Catchy title that includes the date")
    intro: str = Field(description="1-2 sentence framing of the day")
    meta_description: str = Field(description="SEO meta description, max 155 chars")
    stories: list[Story]
    narration_script: str = Field(
        description="Smooth spoken-word version of the digest (reserved for future audio)"
    )
