export const SITE_NAME = "The Morning Build";
export const SITE_TAGLINE = "The day's tech news, distilled.";
export const SITE_DESCRIPTION =
  "The day's tech news, distilled. The AI and tech stories that matter each morning: " +
  "what happened, why it matters, and what to watch next. Read it in two minutes.";

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
