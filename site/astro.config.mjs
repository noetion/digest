// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import rehypeRaw from "rehype-raw";
import { unified } from "@astrojs/markdown-remark";

// Set to the deployed URL (also update SITE_URL in the pipeline .env / repo vars).
export const SITE_URL = "https://themorningbuild.com/";

export default defineConfig({
  site: SITE_URL,
  trailingSlash: "always",
  integrations: [sitemap()],
  markdown: {
    // Generated and archived Markdown crosses the same HTML trust boundary.
    processor: unified({
      rehypePlugins: [rehypeRaw, [rehypeSanitize, {
        ...defaultSchema,
        tagNames: [...defaultSchema.tagNames, "small"],
      }]],
    }),
  },
});
