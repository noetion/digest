// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

// Set to the deployed URL (also update SITE_URL in the pipeline .env / repo vars).
export const SITE_URL = "https://example.com";

export default defineConfig({
  site: SITE_URL,
  trailingSlash: "always",
  integrations: [sitemap()],
});
