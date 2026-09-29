import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { constants } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";

const site = fileURLToPath(new URL("../", import.meta.url));
const title = 'Test </ScRiPt><script id="injected-title">alert(1)</script> & "quotes"';
const description = "Line one\nLine two & <angle>\u2028\u2029";
let root;
let html;

before(async () => {
  root = await mkdtemp(join(tmpdir(), "digest-rendering-"));
  await cp(join(site, "src"), join(root, "src"), {
    recursive: true,
    filter: (path) => !path.includes("/content/digests"),
  });
  await cp(join(site, "astro.config.mjs"), join(root, "astro.config.mjs"));
  await cp(join(site, "package.json"), join(root, "package.json"));
  await cp(join(site, "node_modules"), join(root, "node_modules"), {
    recursive: true, mode: constants.COPYFILE_FICLONE,
  });
  await mkdir(join(root, "src/content/digests"), { recursive: true });
  await writeFile(join(root, "src/content/digests/2026-01-01.md"), `---
title: ${JSON.stringify(title)}
description: ${JSON.stringify(description)}
date: 2026-01-01
tags: [ai]
storyCount: 1
readingTimeMinutes: 1
---
## A normal story

Ordinary **bold** prose and [source](https://example.com/report?a=1&b=2).

<small>Sources: <a href="https://example.com/source">Source outlet</a></small>

<small>Sources: [example.com](https://example.com/archive-source)</small>

<img src="x" onerror="alert(2)">
<script id="injected-body">alert(3)</script>
<a href="javascript:alert(4)">Unsafe link</a>
<iframe src="https://example.com"></iframe>
<svg onload="alert(5)"></svg>
<p id="location">Named content</p>
`);
  const astro = JSON.parse(await readFile(join(root, "node_modules/astro/package.json"), "utf8"));
  execFileSync(process.execPath, [join(root, "node_modules/astro", astro.bin.astro), "build"], {
    cwd: root, stdio: "pipe", timeout: 120_000,
  });
  html = await readFile(join(root, "dist/digest/2026-01-01/index.html"), "utf8");
});

after(async () => { if (root) await rm(root, { recursive: true, force: true }); });

test("JSON-LD preserves generated text without creating executable script elements", () => {
  assert.doesNotMatch(html, /<script\b[^>]*id=["']?injected-title/i);
  const records = [...html.matchAll(/<script\b[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi)]
    .map((match) => JSON.parse(match[1]));
  const article = records.find((record) => record["@type"] === "NewsArticle");
  assert.equal(article.headline, title);
  assert.equal(article.description, description);
});

test("Markdown removes executable HTML while retaining ordinary content and attribution", () => {
  assert.doesNotMatch(html, /<script\b[^>]*id=["']?injected-body|\son(?:error|load)\s*=|href=["']javascript:|<iframe\b|<svg\b/i);
  assert.match(html, /<strong>bold<\/strong>/);
  assert.match(html, /href="https:\/\/example.com\/report\?a=1&#x26;b=2"/);
  assert.match(html, /href="https:\/\/example.com\/source">Source outlet<\/a>/);
  assert.match(html, /href="https:\/\/example.com\/archive-source">example.com<\/a>/);
  assert.match(html, /id="a-normal-story"/);
  assert.match(html, /href="#a-normal-story"/);
  assert.match(html, /id="user-content-location">Named content<\/p>/);
  assert.doesNotMatch(html, /id="location"/);
});

test("production routes, feeds, and generated images survive", async () => {
  for (const path of ["index.html", "archive/index.html", "topics/ai/index.html", "rss.xml", "atom.xml"]) {
    assert.match(await readFile(join(root, "dist", path), "utf8"), /A normal story|Test|2026-01-01/);
  }
  const png = await readFile(join(root, "dist/og/2026-01-01.png"));
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
});
