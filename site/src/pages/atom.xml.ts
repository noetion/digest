import { getCollection } from "astro:content";
import type { APIContext } from "astro";
import { SITE_NAME, SITE_DESCRIPTION } from "../lib/site";

function esc(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export async function GET(context: APIContext) {
  const site = context.site!.toString().replace(/\/$/, "");
  const digests = (await getCollection("digests")).sort(
    (a, b) => b.data.date.valueOf() - a.data.date.valueOf(),
  );
  const updated = digests[0]?.data.date.toISOString() ?? new Date().toISOString();

  const entries = digests
    .map((d) => {
      const url = `${site}/digest/${d.id}/`;
      return `  <entry>
    <title>${esc(d.data.title)}</title>
    <link href="${url}"/>
    <id>${url}</id>
    <updated>${d.data.date.toISOString()}</updated>
    <summary>${esc(d.data.description)}</summary>
  </entry>`;
    })
    .join("\n");

  const xml = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>${esc(SITE_NAME)}</title>
  <subtitle>${esc(SITE_DESCRIPTION)}</subtitle>
  <link href="${site}/atom.xml" rel="self"/>
  <link href="${site}/"/>
  <id>${site}/</id>
  <updated>${updated}</updated>
${entries}
</feed>`;

  return new Response(xml, {
    headers: { "Content-Type": "application/atom+xml; charset=utf-8" },
  });
}
