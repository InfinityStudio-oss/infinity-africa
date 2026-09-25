import "server-only";

/**
 * Whether the mock auth fallback (mock-store.ts / mock-session.ts) may be
 * used at all.
 *
 * That fallback exists so the app still runs when Supabase Auth is
 * unreachable in local development. It is not a second authentication
 * system: it performs no email verification, has no rate limiting, and its
 * session cookie is an unsigned user id — the comments on those modules
 * say as much. None of that belongs anywhere near production, where a real
 * Supabase outage should surface as a failed login rather than quietly
 * switching to a weaker way of deciding who someone is.
 *
 * Locked to non-production deliberately, rather than left to depend on the
 * mock store happening to be empty. Nothing currently writes to that store,
 * so the path is unreachable today; this makes it stay unreachable if a
 * future change adds a writer.
 */
export function mockAuthEnabled(): boolean {
  return process.env.NODE_ENV !== "production";
}
