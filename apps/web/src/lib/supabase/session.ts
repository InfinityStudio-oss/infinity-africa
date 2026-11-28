import "server-only";

import { cache } from "react";

import { createClient } from "./server";

/**
 * The current request's authenticated user, or null.
 *
 * Deliberately calls `auth.getUser()`, not `auth.getSession()`: getSession()
 * just reads the (possibly stale, unverified) session cookie, while
 * getUser() re-validates the JWT against Supabase Auth. Any server-side
 * authorization decision must use this, not the raw cookie contents.
 *
 * Wrapped in React's `cache` so a layout and the page inside it share one
 * revalidation instead of each making their own. That call goes over the
 * network to Supabase Auth, and the portal renders in Frankfurt while the
 * merchants are in Tanzania, so a duplicate is not free. The memo is
 * scoped to a single request and is never shared between them - see
 * node_modules/next/dist/docs/01-app/01-getting-started/06-fetching-data.md,
 * "Reusing data with React.cache".
 *
 * This is a dedupe, not a cache of the answer: every request still
 * revalidates the JWT exactly once.
 */
export const getSession = cache(async function getSession() {
  const supabase = await createClient();
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();

  if (error || !user) {
    return null;
  }

  return { user, supabase };
});

/**
 * The current request's Supabase access token, for attaching to
 * `Authorization: Bearer <token>` when calling apps/api from a Server
 * Component or Server Action. Reads the (already-cookie-validated) session
 * rather than re-running getUser(), since the caller already knows there's
 * a signed-in user by this point.
 *
 * Also request-scoped with `cache`: a page that makes three API calls
 * built a Supabase client and re-read the cookie jar three times for the
 * same string.
 */
export const getAccessToken = cache(async function getAccessToken(): Promise<string | null> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  return session?.access_token ?? null;
});
