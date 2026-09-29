import type { SupabaseClient } from "@supabase/supabase-js";

export type RecoveryLinkOutcome =
  | { status: "ready" }
  | { status: "invalid"; errorDescription: string | null; carriedParams?: string[] };

/**
 * The parameter NAMES a link arrived with — never their values.
 *
 * "This link is invalid or has expired" is unfalsifiable on its own: it
 * looks identical whether the provider rejected a real token, or the URL
 * turned up carrying nothing at all. Those have completely different
 * causes and completely different fixes, and telling them apart used to
 * mean reading the source. Naming the parameters present separates them
 * at a glance, for whoever is holding the phone.
 *
 * Names only. A token value in the page body would be a secret rendered
 * into the DOM, screenshotted into a support thread and pasted into a
 * chat — which is exactly how single-use tokens leak.
 */
function carriedParamNames(query: URLSearchParams, hashParams: URLSearchParams): string[] {
  const names = new Set<string>();
  for (const key of query.keys()) names.add(key);
  for (const key of hashParams.keys()) names.add(key);
  return [...names];
}

/**
 * Establishes the session a recovery/invite link is supposed to carry —
 * explicitly, exactly once. This exists because @supabase/ssr's
 * createBrowserClient (apps/web/src/lib/supabase/client.ts) hardcodes
 * `flowType: "pkce"` (it spreads that field into the auth options *after*
 * any caller-supplied value, so it can never be overridden) and defaults
 * `detectSessionInUrl` to true in a browser. The backend generates every
 * reset/invite link via `auth.admin.generate_link()`
 * (app/services/email.py), which is a server-side call with no browser
 * code_verifier available — it can only ever produce an implicit-style
 * link (Supabase's own /auth/v1/verify redirects back to us with
 * `#access_token=...&refresh_token=...&type=recovery`), never a PKCE
 * `?code=`. Under `flowType: "pkce"`, auth-js's own session-from-URL
 * logic refuses that implicit-style callback (throws internally, session
 * never saved) — so the very first `updateUser()` call always failed with
 * "Auth session missing!", which the UI's own `.includes("session")`
 * check turned into "invalid or has expired", on every link, including
 * one opened within seconds. Confirmed live 2026-08-29.
 *
 * Handles all three shapes Supabase can hand back, per which one the URL
 * actually carries:
 *  - `?code=...`                              -> exchangeCodeForSession
 *  - `?token_hash=...` (+ this page's own fixed, expected type)
 *                                              -> verifyOtp
 *  - `#access_token=...&refresh_token=...`     -> setSession
 * `allowedOtpTypes` bounds which OTP types the token_hash branch will
 * even attempt for this page (the reset-password page only ever expects
 * "recovery"; the invite-accept page expects "invite" for a first-time
 * invite but "recovery" too, since resend-invite
 * (app/routers/merchant_portal.py's resend-invite endpoint) reuses the
 * recovery link type for an already-existing user — invite links only
 * work once, per Supabase's own design). The URL's own `type` value is
 * only ever used if it's in this allowed set for the calling page —
 * Supabase's own verifyOtp still independently validates that token_hash
 * actually was issued for that exact type, so a mismatched/forged type
 * simply fails there regardless.
 */
export async function establishRecoveryLinkSession(
  supabase: SupabaseClient,
  { allowedOtpTypes }: { allowedOtpTypes: readonly ("recovery" | "invite")[] },
): Promise<RecoveryLinkOutcome> {
  const url = new URL(window.location.href);
  const query = url.searchParams;
  const hashParams = new URLSearchParams(url.hash.startsWith("#") ? url.hash.slice(1) : url.hash);

  // Supabase rejected the link outright (expired, already used, revoked)
  // — it redirects with #error=...&error_description=... instead of a
  // working session. Checked first: none of the exchange methods below
  // would find a usable token on a link shaped like this anyway.
  const errorDescription = hashParams.get("error_description") ?? query.get("error_description");
  if (errorDescription) {
    return { status: "invalid", errorDescription: errorDescription.replace(/\+/g, " ") };
  }

  const code = query.get("code");
  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    scrubLinkParamsFromUrl();
    return error ? { status: "invalid", errorDescription: error.message } : { status: "ready" };
  }

  const tokenHash = query.get("token_hash") ?? hashParams.get("token_hash");
  const rawType = query.get("type") ?? hashParams.get("type");
  const otpType = allowedOtpTypes.find((allowed) => allowed === rawType);
  if (tokenHash && otpType) {
    const { error } = await supabase.auth.verifyOtp({ type: otpType, token_hash: tokenHash });
    scrubLinkParamsFromUrl();
    return error ? { status: "invalid", errorDescription: error.message } : { status: "ready" };
  }

  const accessToken = hashParams.get("access_token");
  const refreshToken = hashParams.get("refresh_token");
  if (accessToken && refreshToken) {
    const { error } = await supabase.auth.setSession({ access_token: accessToken, refresh_token: refreshToken });
    scrubLinkParamsFromUrl();
    return error ? { status: "invalid", errorDescription: error.message } : { status: "ready" };
  }

  // No recognizable token in the URL at all — a stale bookmark, this
  // exact link opened a second time after the URL was already scrubbed
  // once, or a direct navigation with nothing attached. Never treated as
  // success just because there's nothing to actively reject.
  //
  // The provider rejected nothing here, so there is no message to show.
  // Report what the URL did carry instead: this branch and a genuinely
  // expired token produce the same words otherwise, and they are not the
  // same problem.
  return {
    status: "invalid",
    errorDescription: null,
    carriedParams: carriedParamNames(query, hashParams),
  };
}

function scrubLinkParamsFromUrl(): void {
  // A single-use token must not still be sitting in the address bar (or
  // browser history) after it's been consumed — a page refresh, or the
  // merchant re-opening the same emailed link a second time, would
  // otherwise attempt to consume it again and always fail the second
  // time. replaceState doesn't reload the page, so the session this
  // function just established in memory survives.
  window.history.replaceState(null, "", window.location.pathname);
}
