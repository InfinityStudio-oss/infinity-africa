/** Reporting dates, in the timezone the business actually runs in.
 *
 * Every dashboard figure on this platform is a Dar es Salaam calendar
 * day, not a UTC one. The two differ by three hours, so a UTC day
 * boundary cuts a Tanzanian evening in half and moves that evening's
 * takings onto the wrong day.
 *
 * These were local to components/merchant/overview-dashboard.tsx. The
 * Super Admin dashboard needs the same ones, and two copies of a
 * timezone rule is how the two portals start disagreeing about what
 * "today" means.
 */

const TIMEZONE = "Africa/Dar_es_Salaam";

/** `YYYY-MM-DD` for the given instant, as a Dar es Salaam calendar day. */
export function dayInDarEsSalaam(date: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "01";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** The Dar es Salaam calendar day `days` days before today. */
export function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return dayInDarEsSalaam(date);
}

/** The most recent `count` Dar es Salaam days, oldest first. */
export function recentDays(count: number): string[] {
  return Array.from({ length: count }, (_, index) => daysAgo(count - 1 - index));
}

/**
 * The instants a Dar es Salaam calendar day starts and ends, as strings
 * the API's `date_from`/`date_to` filters understand.
 *
 * Those filters compare against `created_at`, which is stored in UTC, so
 * passing a bare `YYYY-MM-DD` would silently ask for a UTC day and
 * report the wrong takings by three hours' worth of evening.
 *
 * The offset is written out rather than converted by hand because EAT is
 * UTC+3 year round with no daylight saving, so there is exactly one
 * correct offset and no arithmetic to get wrong.
 *
 * `to` is inclusive, matching the API's own documented semantics
 * (`lte`), hence 23:59:59.999 rather than the next midnight.
 */
export function darEsSalaamDayBounds(day: string): { from: string; to: string } {
  return { from: `${day}T00:00:00.000+03:00`, to: `${day}T23:59:59.999+03:00` };
}
