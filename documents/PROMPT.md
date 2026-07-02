# Build Prompt: Automated Daily AI/Tech News Digest Platform

> Paste everything below this line into your AI coding agent to build the project.

---

Act as a principal-level engineer with deep expertise in three areas: Python automation pipelines, LLM cost/quality engineering, and modern front-end development with a strong eye for editorial design and SEO.

I want you to build a **fully automated daily AI/tech news digest platform**. Every day, with zero human involvement, it must:

1. Fetch the latest AI/tech news from multiple RSS feeds.
2. Extract and clean the full article text.
3. Use a two-stage, token-efficient LLM pipeline to select the most important stories and synthesize them into a high-quality daily digest.
4. Publish the digest to a modern, beautiful, SEO-optimized static website that auto-deploys.
5. Optionally cross-post to Dev.to for reach.

Build the complete, production-ready project as described below. Do not simplify or skip stages.

## Project name

Use **"The Context Window"** as the working site name (tagline: *"Your daily 2-minute brief on AI and tech."*). Keep the name in a single config constant / site config file so it can be rebranded in one edit. Alternative candidates to keep in a comment: "Signal & Noise", "Compile Daily", "The Daily Diff", "Wavelength".

## Repository layout (monorepo)

```
context-window/
├── pipeline/                 # Python digest pipeline (uv-managed)
│   ├── pyproject.toml
│   ├── src/digest/
│   │   ├── __init__.py
│   │   ├── config.py         # pydantic-settings configuration
│   │   ├── feeds.py          # RSS fetching
│   │   ├── extract.py        # full-text extraction + trimming
│   │   ├── dedupe.py         # seen-URL state + same-story clustering
│   │   ├── triage.py         # Stage A: cheap story ranking
│   │   ├── synthesize.py     # Stage B: digest generation (structured output)
│   │   ├── render.py         # JSON -> markdown post for the site
│   │   ├── publish.py        # git commit + optional Dev.to cross-post
│   │   ├── costs.py          # token accounting + budget guard
│   │   └── main.py           # orchestrator (python -m digest.main)
│   └── tests/
├── site/                     # Astro website
├── data/
│   └── seen.json             # dedup state, committed by the pipeline
├── .github/workflows/daily-digest.yml
├── .env.example
└── README.md
```

Python 3.12+, managed with `uv` (lockfile committed). Lint/format with `ruff`. Full type hints, `mypy --strict` clean.

---

## Stage 1 — Configuration

- Use `pydantic-settings` to load config from environment / `.env`:
  - `OPENAI_API_KEY` (required)
  - `DEV_TO_API_KEY` (optional — cross-posting is skipped with a warning if absent)
  - `MAX_STORIES` (default 6), `MAX_ARTICLE_WORDS` (default 1800), `DAILY_COST_CAP_USD` (default 0.25)
  - `DRY_RUN` (default false — when true, run everything but write to `./out/` instead of committing/publishing)
- Feed list as a typed constant (name, url, default topic tag). Start with these **actual RSS endpoints** (note: category pages are not feeds — always use the `/feed/` URLs):
  - TechCrunch AI: `https://techcrunch.com/category/artificial-intelligence/feed/`
  - The Verge: `https://www.theverge.com/rss/index.xml`
  - Ars Technica: `https://feeds.arstechnica.com/arstechnica/index`
  - VentureBeat AI: `https://venturebeat.com/category/ai/feed/`
  - Hacker News front page (via hnrss): `https://hnrss.org/frontpage?points=150`
- Provide `.env.example` documenting every variable.

## Stage 2 — Acquisition (RSS to clean, trimmed text)

- Fetch feeds with `feedparser`, but download over `httpx` with explicit timeouts (10s connect / 20s read), a realistic User-Agent, and `tenacity` retry (3 attempts, exponential backoff).
- **Failure isolation is mandatory:** one dead feed or unparseable article logs a warning and is skipped; it must never abort the run.
- Filter to entries published in the **last 24 hours** (fall back to "not in seen state" if a feed lacks dates).
- Deduplicate against `data/seen.json` (canonicalized URL hash + ISO date; prune entries older than 14 days).
- Extract full text with **`trafilatura`** (`extract(html, output_format="markdown", include_links=False, include_images=False, include_comments=False)`). Do not use newspaper3k (unmaintained) or html2text (unnecessary — trafilatura outputs markdown directly).
- **Token-efficiency trimming (do this before any LLM call — it is the biggest cost lever):**
  - Truncate each article to `MAX_ARTICLE_WORDS` words, cutting at a paragraph boundary.
  - Strip trailing boilerplate: "Related articles", newsletter signups, author bios (heuristic: drop trailing paragraphs under 20 words that contain no sentence-ending punctuation).
  - Collapse repeated whitespace.

## Stage 3 — LLM synthesis (two-stage, cost-engineered)

Use the official `openai` Python SDK (Responses API).

### Stage A — Triage with `gpt-5-nano`

- Input: only headline + first ~80 words of each candidate article (never the full text — this stage exists to avoid paying for full articles that won't make the cut).
- `reasoning: {"effort": "minimal"}`, structured output.
- Task: (1) cluster entries that cover the same underlying story across different feeds, (2) score each cluster 1–10 on significance to engineers/AI practitioners, (3) return the top `MAX_STORIES` clusters with a one-line reason each.
- Only the winning clusters' articles proceed to Stage B; for a cluster with multiple sources, pass the longest extraction as primary text and the other headlines+URLs as corroborating sources.

### Stage B — Synthesis with `gpt-5-mini`

- `reasoning: {"effort": "low"}`, `max_output_tokens` set to a sane cap (~4000).
- **Structured outputs with a Pydantic schema** — never ask the model to emit markdown directly. Schema:

```python
class Story(BaseModel):
    headline: str            # H2-ready, written like a searchable news headline
    what_happened: str       # bullet 1: the facts
    why_it_matters: str      # bullet 2: technical impact for engineers
    outlook: str             # bullet 3: context / what to watch next
    source_urls: list[str]   # every claim must be traceable to these
    topic_tag: str           # one of: ai, chips, startups, big-tech, dev-tools, policy

class Digest(BaseModel):
    title: str               # catchy, includes the date
    intro: str               # 1-2 sentence framing of the day
    meta_description: str    # <=155 chars, for SEO
    stories: list[Story]
    narration_script: str    # smooth spoken-word version of the digest (reserved for the future audio feature)
```

- **Prompt-caching discipline:** the system prompt (editorial persona, rules, schema description, style examples) must be a byte-identical static constant placed *first* in every request; all dynamic content (date, articles) comes after it. OpenAI automatically bills the repeated prefix at ~90% off — do not interpolate anything dynamic into the system prompt.
- Editorial rules in the system prompt:
  - Voice: sharp, technical, zero fluff — written for engineers, not general consumers.
  - Ground every statement strictly in the provided source text; if the sources don't say it, don't write it.
  - No sensationalism; numbers and concrete details over adjectives.
- Do **not** use the Batch API (24h latency defeats a daily-news product) and do not set `temperature` (reasoning models ignore/reject it — faithfulness comes from grounding rules + structured output).

### Cost accounting (`costs.py`)

- After each API call, read the `usage` object and log input / cached-input / output (incl. reasoning) token counts and estimated USD cost (keep prices in one constants dict).
- Accumulate per-run cost; if it would exceed `DAILY_COST_CAP_USD`, abort before the next call with a clear error. Expected normal cost: $0.01–0.03/run.

## Stage 4 — The website (Astro)

Build a static blog in `site/` with **Astro** (content collections). This is a flagship deliverable — treat design and SEO as first-class, not an afterthought.

### Publishing flow

- `render.py` converts the `Digest` JSON into an MDX/markdown file at `site/src/content/digests/YYYY-MM-DD.md` with frontmatter:

```yaml
title: ...
date: 2026-07-02
description: <meta_description>
tags: [ai, chips, ...]        # union of story topic_tags
storyCount: 6
readingTimeMinutes: 2
audio: null                    # reserved: future TTS mp3 URL
sources: [...]                 # all source URLs
```

- The digest body renders each story as an H2 + exactly three labelled bullets (**What happened / Why it matters / Outlook**) + a small "Sources" link row.
- The raw `Digest` JSON is also saved to `site/src/content/digests/YYYY-MM-DD.json` — future email and audio features will consume this JSON, so it is the canonical artifact.
- `publish.py` commits the new files + updated `seen.json` and pushes; the host (Vercel or Cloudflare Pages — document both, recommend Cloudflare Pages free tier) auto-deploys on push.

### SEO requirements (all mandatory)

- Semantic HTML (`<article>`, `<time>`, proper heading hierarchy), one H1 per page.
- Canonical URL, unique `<title>` (≤60 chars) and meta description per page.
- JSON-LD structured data: `NewsArticle` on digest pages, `WebSite` + `Organization` on the homepage.
- Open Graph + Twitter card tags, with **auto-generated OG images** per digest (satori or `astro-og-canvas`: date + top headlines on branded background).
- `@astrojs/sitemap` for `sitemap.xml`, plus `robots.txt`.
- Site's own RSS + Atom feed (`@astrojs/rss`) — a news site must be subscribable.
- Clean date URLs: `/digest/2026-07-02/`; archive paginated by month at `/archive/`; tag pages at `/topics/ai/` etc.
- Internal linking: each digest links to the previous/next digest.
- Performance budget: Lighthouse ≥95 on all four categories. Static HTML with zero client-side JS except the theme toggle; self-hosted subset fonts with `font-display: swap`; explicit dimensions on all images (no layout shift).

### UI/UX requirements

- Editorial, minimal, typography-first design — think a modern newsletter site (Stratechery / TLDR / Vercel blog energy), not a generic template.
- Fonts: Inter or Geist for UI, with a distinctive display font for the masthead; comfortable measure (~65ch), generous line height.
- **Dark mode by default**, honoring `prefers-color-scheme`, with a no-flash toggle (inline script sets the class before paint).
- Homepage: masthead + today's digest in full + a compact archive strip of recent days.
- Digest page: date, reading time and story-count badges; sticky mini table of contents (story headlines) on desktop; prev/next navigation.
- A visible **"Get this by email" subscribe form placeholder component** (non-functional for now, wired in Phase 2) on the homepage and each digest.
- Accessibility: WCAG AA contrast in both themes, skip-to-content link, visible focus states, reduced-motion respect.
- Astro view transitions between pages for a polished feel.

## Stage 5 — Automation (GitHub Actions)

Create `.github/workflows/daily-digest.yml`:

- `schedule: cron "0 6 * * *"` (06:00 UTC daily) + `workflow_dispatch` for manual runs.
- `concurrency: { group: daily-digest, cancel-in-progress: false }` so runs can never overlap/double-publish.
- Steps: checkout → setup uv + cached deps → run pipeline → commit & push (built-in `GITHUB_TOKEN` with `contents: write`).
- **Idempotency:** the pipeline exits 0 with a "already published today" message if `site/src/content/digests/<today>.md` exists.
- **Failure alerting:** on job failure, automatically open (or update) a GitHub issue labeled `pipeline-failure` with the log tail. Silent failure is unacceptable.
- Secrets: `OPENAI_API_KEY`, `DEV_TO_API_KEY` in repo secrets; document setup in the README.

### Optional Dev.to cross-post

- POST to `https://dev.to/api/articles` (note: the API path, not the site root) with header `api-key`, payload `{"article": {"title": ..., "body_markdown": ..., "published": true, "tags": ["ai", "news", "programming", "technology"], "canonical_url": "<link to our site>"}}`.
- **Always set `canonical_url` to our own site's digest URL** so the website keeps the SEO credit.
- Skip gracefully with a log line if the key is absent.

## Roadmap (do not build now, but architect for it)

These are why the structured `Digest` JSON is the canonical artifact:

- **Phase 2 — Daily email:** an email renderer consumes the same JSON via a react-email/MJML template; provider: Buttondown or Resend broadcasts (both have free tiers). The subscribe form placeholder gets wired to the provider's API. No pipeline changes needed beyond one new render+send module.
- **Phase 3 — Paid audio digests:** the `narration_script` field is already generated. A TTS module (OpenAI TTS or ElevenLabs) produces an MP3 per digest, uploaded to object storage; the reserved `audio` frontmatter field lights up an `<audio>` player on the post and a podcast RSS feed. Paid tier via Stripe with an auth-gated private feed URL.

## Quality bar

- Full type hints; `ruff` + `mypy --strict` clean.
- Unit tests (pytest) for: feed-entry filtering, trimming logic, dedup state, markdown rendering from a fixture `Digest` JSON, cost-cap guard, and Dev.to payload construction (mock all network I/O).
- Structured logging (`logging` with a concise formatter): per-stage timing, article counts, token/cost summary line at the end of every run.
- README covering: architecture diagram, local setup (`uv sync`, `.env`), dry-run instructions, GitHub secrets setup, deployment to Cloudflare Pages/Vercel, and the roadmap.
