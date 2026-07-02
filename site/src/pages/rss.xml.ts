import rss from "@astrojs/rss";
import { getCollection } from "astro:content";
import type { APIContext } from "astro";
import { SITE_NAME, SITE_DESCRIPTION } from "../lib/site";

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
      pubDate: d.data.date,
      link: `/digest/${d.id}/`,
      categories: d.data.tags,
    })),
    customData: "<language>en-us</language>",
  });
}
