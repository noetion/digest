import type { APIContext } from "astro";

export function GET(context: APIContext) {
  const body = `User-agent: *
Allow: /

Sitemap: ${new URL("sitemap-index.xml", context.site)}
`;
  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
