import "server-only";

/**
 * Whether the authentication-free UI preview mode may be used.
 *
 * `__PORTAL_UI_PREVIEW__` exists so the portal and Super Admin shells can
 * be rendered locally without a session, for design work. Where it is
 * honoured it skips `requireSuperAdmin()` / `requireUser()` outright, so
 * the variable being set is the difference between the Super Admin console
 * requiring a platform account and requiring nothing at all.
 *
 * An environment variable should never be able to do that in production —
 * not through a mistaken Vercel setting, not through a compromised CI
 * variable, not through a copied deploy config. Requiring a non-production
 * NODE_ENV keeps the design workflow working locally while removing it as
 * a production authentication bypass.
 */
export function uiPreviewEnabled(): boolean {
  return process.env.NODE_ENV !== "production" && Boolean(process.env.__PORTAL_UI_PREVIEW__);
}
