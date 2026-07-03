# Platform Hardening: July 2026 Improvements

A deep evaluation of the platform after its first real publishing day surfaced a set of
weaknesses. None had bitten yet, but each was a matter of time. This document records
what changed and why it matters.

## The theme

The platform runs unattended. Nobody is watching the pipeline at 6am, and nobody
proofreads the output before it publishes. That means every gap falls into one of two
dangerous categories:

1. **Silent absence.** The digest doesn't publish and nobody notices until later.
2. **Silent degradation.** Something low-quality publishes under the brand.

Most of these changes exist to convert both categories into either self-healing
behavior or loud, visible failure.

---

## Reliability fixes (pipeline)

### 1. Retry cron in the daily workflow

**Before:** one scheduled run at 06:00 UTC. **After:** a second attempt at 07:30 UTC.

GitHub Actions cron is best-effort. Scheduled runs are regularly delayed and are
occasionally skipped outright when runner pools are busy. With a single attempt, one
skipped trigger means no digest that day, and the failure alert never fires because
nothing failed: the run simply never happened.

The pipeline's idempotency guard (exit cleanly if today's file exists) makes retries
free. If the 06:00 run succeeded, the 07:30 run is a no-op costing a few seconds of
compute. If it was skipped or failed transiently, the 07:30 run publishes the digest.
One line of YAML buys a second chance every single day.

### 2. Feed freshness window widened from 24h to 48h

**Before:** articles older than 24 hours were discarded at fetch time.
**After:** the window is 48 hours.

The old window had a hidden coupling with failure: if a day's run failed completely,
that day's stories were older than 24 hours by the next morning and were filtered out
forever. A one-day outage silently became a one-day hole in coverage *plus* a set of
stories that never got covered at all.

The dedup state (`data/seen.json`) already guarantees no story is used twice, so the
wider window introduces zero duplication risk. Its only effect is that after a bad
day, the next digest can still pick up what was missed.

### 3. Triage output cap raised (2,000 → 6,000 tokens) and prompt slimmed

**Before:** triage was instructed to return *every* candidate in a cluster, with a
2,000-token output cap. **After:** it only returns clusters that are plausible digest
material, with a 6,000-token cap.

This was a latent crash. On a busy news day the feeds produce 60-80 candidates, and a
JSON structure enumerating all of them can exceed 2,000 tokens. A truncated structured
output fails Pydantic parsing and kills the entire run. The failure would look random:
fine on quiet days, dead on exactly the days with the most news.

The fix attacks both sides: the prompt no longer demands exhaustive output (candidates
that are clearly not digest material are simply omitted), and the cap has generous
headroom. gpt-5-nano output costs $0.40 per million tokens, so the extra headroom
costs fractions of a cent in the worst case.

### 4. Rebase before push in CI

**Before:** the workflow committed and pushed directly. **After:** it runs
`git pull --rebase origin main` first.

If anything lands on `main` while the pipeline runs (a manual fix, a merged PR), the
bot's push is rejected and the digest is stranded in a dead runner workspace. The
rebase makes the publish step tolerant of concurrent activity on the branch.

---

## Content quality safeguards (pipeline)

### 5. Pre-publish quality gate (`quality.py`)

The failure alerting only fired when the pipeline *crashed*. A digest that parsed
correctly but was hollow (one thin story, an empty "why it matters", a three-sentence
narration script) would publish without a whisper. For a product whose entire value
proposition is editorial quality, this was the largest unguarded surface.

`check_quality()` now runs between synthesis and rendering, and blocks publishing
when:

- fewer than 2 stories made the cut
- any headline, bullet, or the intro is under a minimum length
- any story has no source URLs
- the narration script is under 100 words

A blocked publish raises, which fails the run, which opens the GitHub issue. A human
decides whether to re-run or investigate. The judgment call embedded here: **it is
better to miss a morning than to publish something embarrassing.** Readers forgive a
gap; they screenshot a broken briefing.

### 6. Slop-vocabulary detector (same module, warnings only)

The synthesis prompt bans the vocabulary that reads as machine-written ("delve",
"seamless", "game-changer", "leverage" and friends). But prompts are soft constraints,
and models drift. The quality gate now scans every published field against the banned
list and logs a warning per hit.

Deliberately *not* a publish blocker: one slip in a headline is tolerable, and
auto-rewriting risks mangling meaning. The point is visibility. A pattern of warnings
across a week of Actions logs is the signal to tighten the prompt, caught in days
instead of after a reader tweets about it.

### 7. Cluster remapping extracted and tested (and a real bug fixed)

The trickiest code in the pipeline maps triage's cluster indices onto the smaller
list of articles that survived full-text extraction. It lived inline in `main()` with
zero test coverage.

Writing the tests exposed an actual off-by-one class bug: the old code built its index
map from the *pre-extraction* winner positions, so when an article in the middle of
the list failed extraction (paywall, empty body), every cluster pointing at a later
article silently pointed at the *wrong article*. The digest would then synthesize a
story attributed to the wrong source URL. This is exactly the kind of bug that
produces plausible-looking wrong output, the worst failure mode for a news product.

The logic is now a pure function (`remap_clusters`) that matches by URL instead of
positional arithmetic, with four tests covering the survival, partial-failure,
full-failure, and empty cases.

---

## Site improvements

### 8. Custom 404 page

The deleted sample digest (`/digest/2026-07-01/`) and any mistyped URL landed on
Cloudflare's unbranded default 404. The new page keeps lost visitors inside the site
with links to today's briefing and the archive. Trivial effort; removes the one page
of the site that looked abandoned.

### 9. About page with AI disclosure

Three reasons this page earns its place:

- **Reader trust.** A news site with no "who is behind this" page reads as a content
  farm, and The Morning Build is fighting that exact perception battle.
- **Honest AI disclosure.** The briefing is AI-assisted and the site now says so
  plainly, including the grounding rule (if the sources don't say it, the briefing
  doesn't either) and the fact that every story links to original reporting. The
  vague footer ("Generated daily.") was technically honest but evasive; evasiveness
  is what erodes trust when discovered.
- **Search quality signals.** Google's E-E-A-T guidance explicitly looks for
  information about who publishes a site. News-adjacent sites without it are at a
  structural disadvantage.

### 10. Full-content RSS feed

The feed previously shipped only the one-line description per digest, forcing a
click-through. The audience is engineers, the demographic most likely to live in an
RSS reader, and the product is a two-minute read. Making them click through defeats
the entire value proposition inside the channel they prefer most.

Feed items now carry the complete rendered briefing (markdown rendered to HTML and
sanitized). The site remains the canonical home; the feed becomes genuinely usable.

### 11. OG image fonts vendored into the repo

`astro-og-canvas` fetched Noto Sans from `api.fontsource.org` on every single build,
visible as a network call in the build logs. That made every deploy dependent on a
third-party API's uptime: if fontsource hiccups, the whole site fails to deploy,
including the daily digest publish. The two font files (~56KB total) now live in
`site/src/fonts/` and builds are fully self-contained.

### 12. Navigation consistency

Topic pages' digest links now use the same full-page navigation attribute as the
homepage and archive, so every route into a digest page renders identically. About
links were added to the header and footer.

---

## Deliberate non-changes

Three findings from the evaluation were intentionally left alone:

- **Homepage showing the full latest digest.** Duplicating content with the permalink
  page slightly dilutes SEO, but "read today's briefing with zero clicks" *is* the
  product promise. An excerpt homepage would optimize a metric at the cost of the
  actual experience. Revisit only if search traffic becomes a primary growth channel.
- **LICENSE file.** Whether this repo should invite reuse is a business decision, not
  a code decision. Left for the owner to decide.
- **Story tiering (lead story + quick hits).** Requires schema, prompt, render, and
  template changes. With one real digest published, there is no evidence yet that
  equal-weight stories are a problem. Worth revisiting after a few weeks of output.

## One manual step: analytics

The site currently has no visibility into whether anyone reads it. Cloudflare Pages
has free, cookie-less Web Analytics that cannot be enabled from the repo:

1. Cloudflare dashboard → your Pages project → **Metrics** (or **Web Analytics**)
2. Enable Web Analytics for `themorningbuild.com`

Cloudflare injects the measurement beacon automatically at the edge; no code change
or cookie banner is needed. Without this, every product decision (story count, length,
publish time) is a guess.

## Verification

- 42 pipeline tests pass (up from 32), including new coverage for the quality gate
  and the remapping bug
- `ruff` and strict `mypy` clean
- Site builds all 9 routes, OG images render from vendored fonts, RSS carries full
  content
