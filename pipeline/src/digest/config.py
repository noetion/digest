"""Configuration: environment settings and feed sources."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Single source of truth for branding. Rebrand the whole project by editing these.
SITE_NAME = "The Morning Build"
SITE_TAGLINE = "The day's tech news, distilled."

# Repo-relative paths (resolved from this file: pipeline/src/digest/config.py -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTENT_DIR = REPO_ROOT / "site" / "src" / "content" / "digests"
SEEN_STATE_PATH = REPO_ROOT / "data" / "seen.json"
DRY_RUN_OUT_DIR = REPO_ROOT / "out"

TRIAGE_MODEL = "gpt-5-nano"
SYNTHESIS_MODEL = "gpt-5-mini"

TOPIC_TAGS = ("ai", "chips", "startups", "big-tech", "dev-tools", "policy")


class Feed(BaseModel):
    """A single RSS source."""

    name: str
    url: str
    topic: str


# Category pages are NOT feeds; these are the actual RSS endpoints.
# Probe freshness: python scripts/probe_feeds.py
FEEDS: tuple[Feed, ...] = (
    Feed(
        name="TechCrunch AI",
        url="https://techcrunch.com/category/artificial-intelligence/feed/",
        topic="ai",
    ),
    Feed(
        name="The Verge",
        url="https://www.theverge.com/rss/index.xml",
        topic="big-tech",
    ),
    Feed(
        name="Ars Technica AI",
        url="https://arstechnica.com/ai/feed/",
        topic="ai",
    ),
    Feed(
        name="VentureBeat",
        url="https://venturebeat.com/feed/",
        topic="ai",
    ),
    Feed(
        name="Hacker News",
        url="https://hnrss.org/frontpage?points=150",
        topic="dev-tools",
    ),
    Feed(
        name="The Decoder",
        url="https://the-decoder.com/feed/",
        topic="ai",
    ),
    Feed(
        name="MIT Technology Review AI",
        url="https://www.technologyreview.com/topic/artificial-intelligence/feed",
        topic="ai",
    ),
    Feed(
        name="Wired AI",
        url="https://www.wired.com/feed/tag/ai/latest/rss",
        topic="ai",
    ),
    Feed(
        name="Google AI Blog",
        url="https://blog.google/technology/ai/rss/",
        topic="ai",
    ),
    Feed(
        name="IEEE Spectrum AI",
        url="https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
        topic="ai",
    ),
    Feed(
        name="Tom's Hardware AI",
        url="https://www.tomshardware.com/feeds/tag/artificial-intelligence",
        topic="chips",
    ),
)

USER_AGENT = (
    "Mozilla/5.0 (compatible; MorningBuildDigest/1.0; +https://themorningbuild.com/)"
)


class Settings(BaseSettings):
    """Environment-driven configuration. See .env.example for documentation."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    dev_to_api_key: str = ""
    max_stories: int = 5
    max_article_words: int = 1800
    daily_cost_cap_usd: float = 0.25
    dry_run: bool = False
    site_url: str = "https://themorningbuild.com"


def load_settings() -> Settings:
    return Settings()
