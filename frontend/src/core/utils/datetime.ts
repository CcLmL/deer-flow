import { formatDistanceToNow } from "date-fns";
import { enUS as dateFnsEnUS, zhCN as dateFnsZhCN } from "date-fns/locale";

import { detectLocale, type Locale } from "@/core/i18n";
import { getLocaleFromCookie } from "@/core/i18n/cookies";

function getDateFnsLocale(locale: Locale) {
  switch (locale) {
    case "zh-CN":
      return dateFnsZhCN;
    case "en-US":
    default:
      return dateFnsEnUS;
  }
}

function resolveLocale(locale?: Locale) {
  return (
    locale ??
    (getLocaleFromCookie() as Locale | null) ??
    // Fallback when cookie is missing (or on first render)
    detectLocale()
  );
}

export function formatTimeAgo(date: Date | string | number, locale?: Locale) {
  const effectiveLocale = resolveLocale(locale);
  // Guard against invalid/empty timestamps (e.g. a backend returning "" for
  // lastUpdated when there are no memories) -- date-fns would throw
  // "Invalid time value" on `new Date("")`. Return a neutral placeholder.
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) {
    return "-";
  }
  return formatDistanceToNow(parsed, {
    addSuffix: true,
    locale: getDateFnsLocale(effectiveLocale),
  });
}

/**
 * Format an absolute date and time for display (e.g. "2026/11/13 14:32").
 * Returns an empty string for invalid or missing timestamps so callers can
 * omit the element instead of rendering a placeholder under a message bubble.
 */
export function formatDateTime(date: Date | string | number, locale?: Locale) {
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat(resolveLocale(locale), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(parsed);
}
