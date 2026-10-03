/**
 * The one place that decides what Sentry is allowed to collect.
 *
 * Shared by the three init files (browser, Node, edge) so the rules
 * cannot drift apart — a privacy setting that is right in two of three
 * runtimes is not a privacy setting.
 *
 * Worth knowing why this is so explicit. Sentry SDK v11 replaced the old
 * single `sendDefaultPii: false` switch with a granular `dataCollection`
 * object whose **defaults are permissive**: cookies, request and
 * response headers, request bodies, URL query parameters, database query
 * data and local variables in stack frames are all collected unless
 * turned off. Every `false` below is therefore load-bearing, not
 * decoration, and removing one silently starts exporting customer data.
 */

export const PRIVACY_DATA_COLLECTION = {
  // Sentry otherwise fills in user.email / user.username / user.ip_address
  // from whatever it can find in the request or the session.
  userInfo: false,
  // Supabase keeps the access and refresh token in a cookie.
  cookies: false,
  // An Authorization header is a merchant's live API key.
  httpHeaders: false,
  // A request body on this platform is a payment, a login, or an
  // onboarding submission carrying NIDA and licence documents.
  httpBodies: [],
  // Reset tokens, OTP codes and `?email=` all arrive as query params.
  urlQueryParams: false,
  // Bound query parameters include the phone number a collection was
  // created for.
  databaseQueryData: false,
  // Arguments passed to background work — a webhook payload, a payout.
  queues: false,
  // The richest accidental leak there is: a stack frame captured
  // mid-payment holds the phone number, the amount, and sometimes the
  // provider credentials.
  stackFrameVariables: false,
  // Source context around the failing line is code, not data, and it is
  // what makes a report readable. Kept.
  frameContextLines: 5,
};
