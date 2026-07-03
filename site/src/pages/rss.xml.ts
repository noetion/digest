import rss from "@astrojs/rss";
import { getCollection } from "astro:content";
import type { APIContext } from "astro";
import MarkdownIt from "markdown-it";
import sanitizeHtml from "sanitize-html";
import { SITE_NAME, SITE_DESCRIPTION } from "../lib/site";

// Engineers disproportionately read via RSS readers, so ship the full story
// content in the feed rather than forcing a click-through for a 2-minute read.
const markdown = new MarkdownIt();

function renderContent(body: string): string {
  return sanitizeHtml(markdown.render(body), {
    allowedTags: [...sanitizeHtml.defaults.allowedTags, "small"],
  });
}

export async function GET(context: APIContext) {
  const digests = (await getCollection("digests")).sort(
    (a, b) => b.data.date.valueOf() - a.data.date.valueOf(),
  );
  return rss({
    title: SITE_NAME,
    description: SITE_DESCRIPTION,
    site: context.site!,
    items: digests.map((d) => ({
      title: d.data.title,
      description: d.data.description,
      content: renderContent(d.body ?? ""),
      pubDate: d.data.date,
      link: `/digest/${d.id}/`,
      categories: d.data.tags,
    })),
    customData: "<language>en-us</language>",
  });
}
