export const SITE_NAME = "The Context Window";
export const SITE_TAGLINE = "Your daily 2-minute brief on AI and tech.";
export const SITE_DESCRIPTION =
  "A fully automated daily digest of the most important AI and tech news, " +
  "written for engineers. What happened, why it matters, and what to watch next.";

export const TOPIC_LABELS: Record<string, string> = {
  ai: "AI",
  chips: "Chips",
  startups: "Startups",
  "big-tech": "Big Tech",
  "dev-tools": "Dev Tools",
  policy: "Policy",
};

export function formatDate(date: Date): string {
  return date.toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function shortDate(date: Date): string {
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}
