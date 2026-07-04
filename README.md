# The Morning Build

*The day's tech news, distilled.*

A fully automated daily news digest platform. Every morning, a Python pipeline reads the day's AI/tech news from multiple RSS feeds, selects the stories that matter to engineers using a two-stage, cost-engineered LLM pipeline, and publishes a structured digest to a fast, SEO-optimized Astro website — with zero human involvement.

## Architecture

```
GitHub Actions (daily cron)
        │
        ▼
┌──────────────────────── pipeline/ ────────────────────────┐
│ fetch RSS feeds → dedup (data/seen.json) → triage          │
│ (gpt-5-nano, headlines only) → extract winners             │
│ (trafilatura, trimmed) → synthesize (gpt-5-mini,           │
│ structured output) → render markdown + canonical JSON      │
└────────────────────────────────────────────────────────────┘
        │  commit to site/src/content/digests/
        ▼
   site/ (Astro) ──auto-deploy──▶ Cloudflare Pages / Vercel
        │
        └──▶ optional Dev.to cross-post (canonical_url → our site)
```

Key design decisions:

- **Token efficiency:** triage sees only headlines + 80-word previews; full text is extracted and trimmed (~1,800 words max) only for winning stories; the static system prompts are byte-identical across runs so OpenAI's prompt caching bills them at ~90% off; `reasoning_effort` and `max_output_tokens` are capped. Typical cost: **$0.01–0.03/run**, with a hard `DAILY_COST_CAP_USD` abort guard.
- **Structured outputs, not markdown-by-LLM:** the model fills a Pydantic schema; Python renders markdown deterministically. The JSON saved next to each post is the canonical artifact that future email and audio features will consume.
- **Failure isolation:** a dead feed or unparseable article logs a warning and is skipped; a Dev.to failure is non-fatal; CI opens a GitHub issue on pipeline failure. A retry cron runs ~90 minutes after the primary only if today's digest is not already on `main`.

## Local setup

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+.

```powershell
# Pipeline
cd pipeline
uv sync
copy ..\.env.example ..\pipeline\.env   # then fill in OPENAI_API_KEY
uv run pytest                            # 69 tests, all offline

# Dry run: full pipeline, writes to ./out/ instead of the site, no publishing
# (set DRY_RUN=true in .env first)
uv run python -m digest.main

# Site
cd ..\site
npm install
npm run dev                              # http://localhost:4321
```

## Deployment

1. **Create a GitHub repo** and push this project.
2. **Host the site** (pick one):
   - **Cloudflare Pages** (recommended, free): create a Pages project from the repo, build command `npm run build`, build output `dist`, root directory `site`.
   - **Vercel:** import the repo, set root directory to `site`, framework preset Astro.
3. **Set the site URL** in two places: `SITE_URL` in `site/astro.config.mjs` and the `SITE_URL` repository variable (Settings → Secrets and variables → Actions → Variables).
4. **Add repository secrets** (Settings → Secrets and variables → Actions → Secrets):
   - `OPENAI_API_KEY` (required)
   - `DEV_TO_API_KEY` (optional — enables cross-posting)
5. Done. The workflow in `.github/workflows/daily-digest.yml` runs on a daily schedule (primary **03:17 UTC**, retry **04:47 UTC** — about **04:15** and **05:45 UK** in BST, **03:15** and **04:45 UK** in GMT). GitHub's cron is best-effort and may delay runs; the retry is a failsafe and skips immediately if today's digest is already committed. You can also trigger a run manually from the Actions tab. Each successful run commits the new digest, which triggers the site deploy.

## Configuration

All pipeline settings are environment variables (see `.env.example`): `MAX_STORIES`, `MAX_ARTICLE_WORDS`, `DAILY_COST_CAP_USD`, `DRY_RUN`, `SITE_URL`. Feed sources live in `pipeline/src/digest/config.py`. Branding (site name/tagline) lives in `pipeline/src/digest/config.py` and `site/src/lib/site.ts`.

## Site features

- Static HTML, zero client JS except the theme toggle — Lighthouse-friendly by construction
- Dark mode by default with system-preference detection and a no-flash toggle
- SEO: canonical URLs, `NewsArticle` JSON-LD, sitemap, robots.txt, per-digest auto-generated OG images, RSS + Atom feeds
- Date-based URLs (`/digest/2026-07-02/`), monthly archive, topic pages, prev/next navigation
- Sticky table of contents on desktop, reading-time and story-count badges
- Accessible: WCAG AA contrast in both themes, skip link, focus states, reduced-motion support

A sample digest used to ship in the repo so the site renders before the first automated run. The pipeline writes a new dated file each day but does not remove the sample; delete any placeholder files manually after the first real digest publishes.

## Roadmap

- **Phase 2 — Daily email:** add a subscribe card on the homepage and digest pages ("Start your day already caught up" / "Get the briefing"), wire it to Buttondown or Resend, and send each digest from the canonical JSON via a new `render_email.py` module. No LLM pipeline changes needed.
- **Phase 2.5 — Social proof:** once the email list has real numbers, add subscriber-count proof to the hero and subscribe box (e.g. "Join N engineers who read The Morning Build") plus a specific reader testimonial. Social proof is the highest-impact conversion lever after benefit-led copy.
- **Phase 3 — Paid audio:** each digest already includes a `narration_script` field and posts reserve an `audio` frontmatter slot. Add a TTS step (OpenAI TTS / ElevenLabs), upload the MP3, and the site's audio player lights up automatically. Gate a private podcast feed behind Stripe.

## Project docs

- [documents/PROMPT.md](documents/PROMPT.md) — the original build specification
- [documents/EVALUATION.md](documents/EVALUATION.md) — architecture decisions and cost analysis
