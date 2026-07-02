import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

const digests = defineCollection({
  // Only .md; the sibling .json files are the canonical artifacts for
  // future email/audio renderers, not site content.
  loader: glob({ pattern: "*.md", base: "./src/content/digests" }),
  schema: z.object({
    title: z.string(),
    date: z.coerce.date(),
    description: z.string(),
    tags: z.array(z.string()),
    storyCount: z.number(),
    readingTimeMinutes: z.number(),
    audio: z.string().nullable().default(null),
    sources: z.array(z.string()).default([]),
  }),
});

export const collections = { digests };
