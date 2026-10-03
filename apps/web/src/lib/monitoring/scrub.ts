/**
 * What may leave the browser in an error report.
 *
 * The mirror of `apps/api/app/core/monitoring.py`, and deliberately a
 * mirror rather than something cleverer: the browser sees the same
 * phone numbers, emails and API keys the backend does, and a payment
 * page URL can carry a reference in its path. A report from the client
 * is just as much an export of customer data as one from the server, so
 * it gets the same treatment.
 *
 * Kept free of any Sentry import so the rules can be unit-tested
 * directly, without a DSN or a browser.
 */

export const REDACTED = "[redacted]";

const SECRET_PATTERNS: RegExp[] = [
  // Merchant API keys and their public counterparts.
  /\b[sp]k_(?:live|test)_[A-Za-z0-9_-]{8,}/gi,
  // Resend keys, if one ever reaches the client by mistake.
  /\bre_[A-Za-z0-9_-]{8,}/g,
  // Anything shaped like a JWT — Supabase access and refresh tokens live
  // in browser storage, so this is the likeliest leak of all.
  /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*/g,
  /\bbearer\s+[A-Za-z0-9._-]{8,}/gi,
  // Email addresses.
  /\b[^\s@]+@[^\s@]+\.[A-Za-z]{2,}\b/g,
  // Tanzanian mobile numbers, in every shape the forms accept.
  /(?:\+?255|\b0)\d{9}\b/g,
  // NIDA: 20 digits, separated or not.
  /\b\d{8}[\s-]?\d{5}[\s-]?\d{5}[\s-]?\d{2}\b/g,
];

/** Query and hash are dropped wholesale: a reset token, an OTP and a
 * `?email=` all arrive that way, and none of them is worth keeping for
 * debugging. The path stays, because the path is the diagnosis. */
export function scrubUrl(url: string): string {
  if (!url) return url;
  const [withoutHash] = url.split("#");
  const [path] = withoutHash.split("?");
  return redactText(path);
}

export function redactText(value: string): string {
  if (!value) return value;
  return SECRET_PATTERNS.reduce((acc, pattern) => acc.replace(pattern, REDACTED), value);
}

const SENSITIVE_KEY_PARTS = [
  "password",
  "secret",
  "token",
  "api_key",
  "apikey",
  "authorization",
  "cookie",
  "pin",
  "nida",
  "phone",
  "msisdn",
  "email",
  "signature",
  "credential",
];

function isSensitiveKey(key: string): boolean {
  const lowered = key.toLowerCase();
  return SENSITIVE_KEY_PARTS.some((part) => lowered.includes(part));
}

/** Depth-limited on purpose: an error payload can contain anything a
 * form held, so an unbounded walk is a hang waiting for a cyclic or
 * deeply nested object. */
function scrubValue(value: unknown, depth = 0): unknown {
  if (depth > 12) return REDACTED;
  if (typeof value === "string") return redactText(value);
  if (Array.isArray(value)) return value.map((item) => scrubValue(item, depth + 1));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isSensitiveKey(key) ? REDACTED : scrubValue(item, depth + 1);
    }
    return out;
  }
  return value;
}

/**
 * Sentry's `beforeSend`, typed loosely so this file needs no Sentry
 * import. Returns null to drop the event — which is also what it does
 * if scrubbing itself fails, because losing a report is better than
 * sending an unscrubbed one.
 */
export function scrubEvent<T extends Record<string, unknown>>(event: T): T | null {
  try {
    const next = event as Record<string, unknown>;

    const request = next.request as Record<string, unknown> | undefined;
    if (request) {
      // A request body on this frontend is a payment form or a login.
      // There is nothing in it worth keeping.
      delete request.data;
      delete request.cookies;
      delete request.query_string;
      if (typeof request.url === "string") request.url = scrubUrl(request.url);
      if (request.headers) delete request.headers;
    }

    // The breadcrumb trail is the richest accidental leak in a browser
    // SDK: every fetch URL, every console.log, every input the user
    // changed. Keep the shape of what happened, scrub the content.
    if (Array.isArray(next.breadcrumbs)) {
      next.breadcrumbs = next.breadcrumbs.map((crumb) => {
        const entry = scrubValue(crumb, 1) as Record<string, unknown>;
        const data = entry?.data as Record<string, unknown> | undefined;
        if (data && typeof data.url === "string") data.url = scrubUrl(data.url);
        return entry;
      });
    }

    if (typeof next.transaction === "string") next.transaction = scrubUrl(next.transaction);

    // The user object is reduced to an id, never redacted field by
    // field. Sentry fills in `email`, `username` and `ip_address` from
    // whatever it can find, and an id — a merchant UUID we issued — is
    // the whole of what is useful for grouping a merchant's errors.
    const user = next.user as Record<string, unknown> | undefined;
    if (user) next.user = user.id ? { id: redactText(String(user.id)) } : undefined;

    for (const key of ["extra", "tags", "contexts", "exception", "message"] as const) {
      if (next[key] !== undefined) next[key] = scrubValue(next[key], 1);
    }

    return next as T;
  } catch {
    return null;
  }
}
