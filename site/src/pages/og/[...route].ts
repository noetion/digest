import { getCollection } from "astro:content";
import { OGImageRoute } from "astro-og-canvas";
import { SITE_NAME, SITE_TAGLINE, formatDate } from "../../lib/site";

const digests = await getCollection("digests");

const pages = Object.fromEntries([
  // Fallback image for the homepage and non-digest pages.
  ["site", { title: SITE_NAME, description: SITE_TAGLINE }],
  ...digests.map((d) => [
    d.id,
    { title: d.data.title, description: `${formatDate(d.data.date)} · ${SITE_TAGLINE}` },
  ]),
]);

export const { getStaticPaths, GET } = OGImageRoute({
  param: "route",
  pages,
  getImageOptions: (_path, page: { title: string; description: string }) => ({
    title: page.title,
    description: page.description,
    bgGradient: [
      [12, 13, 16],
      [22, 30, 44],
    ],
    border: { color: [56, 189, 248], width: 14, side: "inline-start" },
    padding: 72,
    font: {
      title: { size: 64, weight: "Bold", color: [232, 234, 237], lineHeight: 1.15 },
      description: { size: 30, weight: "Normal", color: [154, 160, 171] },
    },
  }),
});
