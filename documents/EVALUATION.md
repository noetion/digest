# Evaluation: What Changed From Your Rough Prompt and Why

A side-by-side of every technical decision in your draft, what replaced it, and the reasoning.

## 1. Single Python file → small structured project

Your draft asked for one `daily_tech_digest.py`. A 500+ line single file is hard to test, extend, and debug — and this project has a roadmap (email, audio) that needs clean seams. The improved prompt specifies a small `src/digest/` package with one module per stage, `uv` for dependency management, `ruff` + `mypy` for quality. Still lightweight: no server, no database (just a JSON state file).

## 2. `newspaper3k` + `html2text` → `trafilatura`

- newspaper3k has been unmaintained since 2020 (its community fork is newspaper4k).
- trafilatura is the benchmark leader for article extraction (F1 ≈ 0.958 on the ScrapingHub benchmark, best overall in the SIGIR 2023 study) and is actively maintained.
- It outputs clean Markdown directly with links/images excluded, so the whole `html2text` step in your draft is deleted — one dependency and one failure point fewer.

## 3. Broken feed URL fixed + multiple sources

`https://techcrunch.com/category/artificial-intelligence/` is an HTML category page, not an RSS feed — `feedparser` would return nothing. The real feed appends `/feed/`. The improved prompt also uses five sources instead of one (TechCrunch AI, The Verge, Ars Technica, VentureBeat AI, Hacker News ≥150 points) with per-feed failure isolation, because a single-source digest is thin and fragile.

## 4. "Top 5 articles" → last-24h filter + dedup + LLM triage

Naively taking the top 5 feed entries re-processes stale articles and misses the actual news of the day. Replaced with: publish-date filter, a persistent seen-URL state file, and a cheap LLM triage stage that clusters duplicate coverage of the same story and ranks by significance.

## 5. `gpt-4o` at temperature 0.2 → two-stage GPT-5 pipeline (token-efficiency core)

Your draft's approach (one big gpt-4o call, temperature 0.2) is both outdated and cost-inefficient. Replaced with:

| Lever | Design | Effect |
|---|---|---|
| Pre-trim articles | Cap at ~1,800 words, strip boilerplate tails before any LLM call | Biggest lever: typically 40–60% input reduction |
| Cheap triage first | `gpt-5-nano` (minimal reasoning) sees only headlines + first 80 words; full text only sent for winners | Never pay mini-rates for articles that won't make the digest |
| Duplicate clustering | Same story from 3 feeds = 1 synthesis input, not 3 | Removes redundant tokens entirely |
| Prompt caching | Static system prompt first, byte-identical every run → OpenAI auto-caches the prefix at ~90% off | Input on repeated prefix: $0.025/M vs $0.25/M |
| Reasoning control | `reasoning_effort: minimal/low` + `max_output_tokens` cap | Reasoning tokens are hidden output billed at $2/M on mini — capping effort cuts them sharply |
| Cost guard | Per-run token/cost logging + hard `DAILY_COST_CAP_USD` abort | A bug can never produce a surprise bill |

Batch API was evaluated and **rejected**: 50% off but up to 24h turnaround, which defeats a daily news product — and at one run/day the absolute savings are pennies.

Also: temperature is gone. Reasoning models don't support it; faithfulness comes from grounding rules + structured outputs instead (the model fills a Pydantic schema; Python renders the markdown deterministically — no malformed-markdown failure mode, and source URLs are enforced per story).

**Expected cost: roughly $0.01–0.03 per day, i.e. under $1/month.**

## 6. Dev.to-only → your own SEO-optimized Astro site (Dev.to demoted to cross-post)

Your stated goal was "a modern, sleek and beautiful website" — the draft never builds one, and publishing exclusively to Dev.to gives Dev.to all the SEO value. Improved design:

- **Astro static site** — the standard for content sites: zero client JS by default, content collections, first-class SEO tooling, free hosting (Cloudflare Pages/Vercel).
- Full technical SEO spec: `NewsArticle` JSON-LD, canonical URLs, sitemap, robots.txt, per-digest auto-generated OG images, its own RSS/Atom feed, date-based URLs, tag + archive pages, Lighthouse ≥95 (Core Web Vitals are a ranking factor).
- UI/UX spec: editorial typography-first design, dark mode default with no-flash toggle, reading-time badges, sticky TOC, WCAG AA accessibility, view transitions.
- Dev.to becomes an optional cross-post **with `canonical_url` pointing at your site**, so you get the reach without donating the SEO. Also fixed the endpoint: the draft's `https://dev.to` would 404 — the API is `https://dev.to/api/articles`.

## 7. Manual run → fully automated GitHub Actions

Daily cron at 06:00 UTC, `workflow_dispatch` for manual re-runs, concurrency group to prevent double-publishing, idempotency guard (exits cleanly if today's digest exists), and automatic GitHub-issue alerting on failure. A git push of the new markdown file is what triggers the site deploy — the pipeline and the site share one repo, so "publish" is just "commit".

## 8. `requests` + bare try/except → `httpx` + `tenacity` + structured logging

Explicit timeouts, exponential-backoff retries, per-article/per-feed failure isolation (one bad source never kills the run), and a per-run summary log line with timings, counts, and cost.

## 9. Future-proofing for email and audio (your roadmap)

The single most important architectural decision for your roadmap: **the digest is stored as structured JSON before it is rendered to markdown**. That makes the future features additive, not rewrites:

- **Email (Phase 2):** an email template consumes the same JSON; Buttondown or Resend broadcasts handle delivery. The site ships with a subscribe-form placeholder from day one.
- **Paid audio (Phase 3):** the schema already includes a `narration_script` field written for spoken delivery, and post frontmatter reserves an `audio` field. Adding TTS (OpenAI TTS / ElevenLabs) + a podcast feed + Stripe gating is one new module, not a refactor.

## 10. Naming

Working name: **The Context Window** — memorable, on-theme for an AI digest, and kept in one config constant so rebranding is a one-line change. Alternates listed in the prompt: Signal & Noise, Compile Daily, The Daily Diff, Wavelength.
