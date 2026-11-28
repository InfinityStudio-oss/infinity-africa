import "server-only";

import { cache } from "react";

import type { DocumentType } from "@infinity/shared";

import { getAccessToken } from "@/lib/supabase/session";

import type {
  MerchantSignupInput,
  MerchantSignupResult,
  OnboardingDocument,
  OnboardingMerchantAccountInput,
  OnboardingMerchantAccountResult,
  OnboardingStatus,
  OnboardingSubmission,
} from "./types";

/**
 * Data-access boundary for the real /v1/onboarding/* and
 * /v1/admin/onboarding/* endpoints — replaces lib/onboarding/store.ts's
 * mock, same shape as lib/portal/api.ts but server-only: every caller here
 * is a Server Component or Server Action (submitOnboardingAction, the
 * onboarding/status pages, the super-admin onboarding review pages), so
 * this can safely use the cookie-based getAccessToken() with no
 * Turbopack client/server bundling conflict.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL;

interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  // `details` is only ever populated on a 422 (app/core/errors.py's
  // RequestValidationError handler) — the raw list of Pydantic field
  // errors. `message` alone is always the generic "Invalid request" for
  // that case, which tells the merchant nothing about what to fix — see
  // firstValidationMessage below.
  error?: { code: string; message: string; details?: unknown };
}

export class OnboardingApiError extends Error {
  code?: string;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

// Pulls the actual reason out of a 422's field-level error list, so the
// merchant sees e.g. "must be a valid Tanzanian phone number..." instead
// of a bare "Invalid request" with no indication of what to fix.
function firstValidationMessage(details: unknown): string | null {
  if (!Array.isArray(details) || details.length === 0) return null;
  const first = details[0];
  if (!first || typeof first !== "object" || typeof (first as { msg?: unknown }).msg !== "string") return null;
  // Pydantic v2 prefixes a field_validator's raised ValueError with
  // "Value error, " — strip it, it's an implementation detail no
  // merchant should see.
  return (first as { msg: string }).msg.replace(/^Value error,\s*/, "");
}

/** `accessToken` is only ever passed explicitly right after a fresh
 * signInWithPassword/signUp call, where reading it back via getAccessToken()
 * would race the cookies the same request just wrote. Every other caller
 * omits it and relies on the already-established session cookie. */
async function authHeader(accessToken?: string): Promise<Record<string, string>> {
  const token = accessToken ?? (await getAccessToken());
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseEnvelope<T>(res: Response): Promise<T> {
  const body: ApiEnvelope<T> = await res.json();
  if (!res.ok || !body.success || body.data === undefined) {
    const message = firstValidationMessage(body.error?.details) ?? body.error?.message ?? "Request failed";
    throw new OnboardingApiError(message, body.error?.code);
  }
  return body.data;
}

// --- Self-service (merchant) -------------------------------------------

/**
 * How long a merchant's onboarding status may be reused without asking
 * the API again.
 *
 * This endpoint is on the critical path of EVERY portal page - the portal
 * layout and four pages await it before rendering anything - and the
 * answer it gives changes perhaps twice in an account's lifetime. Without
 * this, clicking Overview -> Withdrawals -> Invoices costs three
 * identical round trips to Railway, each of which queries Supabase.
 *
 * Ten seconds, not minutes, because two of the states it carries are
 * acted on immediately:
 *
 *   - a Super Admin suspending a business (redirectIfSuspended)
 *   - a Super Admin approving one
 *
 * For up to ten seconds after either, the portal still shows the previous
 * state. That is survivable because this is a UX guard, not the control:
 * apps/api refuses every /v1/merchant/* call from a suspended business
 * regardless of what this says. Raising this value trades directly
 * against how long a suspended merchant keeps seeing a portal whose every
 * panel 403s - which is exactly the "looks like an outage" case
 * lib/onboarding/guard.ts was written to avoid. Do not make it minutes.
 */
const STATUS_TTL_MS = 10_000;

/** Bounded so a long-lived serverless instance serving many merchants
 * cannot grow this without limit. Entries are tiny; the cap is about
 * never being the reason a container runs out of memory. */
const STATUS_CACHE_MAX_ENTRIES = 500;

const statusCache = new Map<string, { storedAt: number; value: OnboardingStatus }>();

/** Keyed by a digest of the access token, never the token itself: the
 * value sits in process memory for ten seconds and there is no reason for
 * a credential to be the thing it is filed under. A digest also means one
 * merchant can never read another's entry - a different session is a
 * different token is a different key. */
async function statusCacheKey(token: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return Buffer.from(digest).toString("base64url");
}

function readStatusCache(key: string): OnboardingStatus | null {
  const hit = statusCache.get(key);
  if (!hit) return null;
  if (Date.now() - hit.storedAt >= STATUS_TTL_MS) {
    statusCache.delete(key);
    return null;
  }
  return hit.value;
}

function writeStatusCache(key: string, value: OnboardingStatus): void {
  const now = Date.now();
  for (const [k, entry] of statusCache) {
    if (now - entry.storedAt >= STATUS_TTL_MS) statusCache.delete(k);
  }
  if (statusCache.size >= STATUS_CACHE_MAX_ENTRIES) {
    // Oldest insertion first — Map preserves it.
    const oldest = statusCache.keys().next();
    if (!oldest.done) statusCache.delete(oldest.value);
  }
  statusCache.set(key, { storedAt: now, value });
}

/** Test seam. Module state outlives a test file, and a status cached by
 * one test would otherwise answer another's request. */
export function __clearOnboardingStatusCache(): void {
  statusCache.clear();
}

/**
 * Returns null on no session, network failure, or a non-2xx response —
 * every caller treats "status unknown" the same as "start onboarding".
 *
 * Deduped per request with React's `cache` (a layout and its page both
 * ask) and reused for STATUS_TTL_MS across requests on the same warm
 * instance.
 *
 * **Only a successful answer is stored.** A null is a failed request or a
 * 401, and caching that would turn one bad second into ten seconds of a
 * verified merchant being bounced to /onboarding.
 */
export const getOnboardingStatus = cache(async function getOnboardingStatus(
  accessToken?: string,
): Promise<OnboardingStatus | null> {
  const token = accessToken ?? (await getAccessToken());
  const key = token ? await statusCacheKey(token) : null;
  if (key) {
    const hit = readStatusCache(key);
    if (hit) return hit;
  }

  try {
    const res = await fetch(`${API_BASE}/v1/onboarding/status`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store",
    });
    if (!res.ok) return null;
    const status = await parseEnvelope<OnboardingStatus>(res);
    if (key) writeStatusCache(key, status);
    return status;
  } catch {
    return null;
  }
});

/** Combined signup — unauthenticated (no Authorization header), sent as
 * multipart/form-data (no file is collected by the Get Started form
 * anymore — KYC documents are handled offline — but the backend endpoint
 * still accepts multipart for its own optional tin_certificate param, so
 * this keeps using FormData rather than switching to JSON). The backend
 * creates the Supabase Auth user itself. Surfaces the backend error
 * `code` (nida_required / nida_invalid / conflict / …) so the caller can
 * attach the message to the right field. */
export async function submitMerchantSignup(input: MerchantSignupInput): Promise<MerchantSignupResult> {
  const fd = new FormData();
  fd.set("full_name", input.full_name);
  fd.set("email", input.email);
  fd.set("password", input.password);
  fd.set("business_name", input.business_name);
  fd.set("nature_of_business", input.nature_of_business);
  fd.set("business_category", input.business_category);
  if (input.physical_address) fd.set("physical_address", input.physical_address);
  if (input.region_city) fd.set("region_city", input.region_city);
  fd.set("contact_phone", input.contact_phone);
  fd.set("nida_number", input.nida_number);
  fd.set("accepted_terms", String(input.accepted_terms));
  fd.set("accepted_privacy", String(input.accepted_privacy));
  if (input.website_url) fd.set("website_url", input.website_url);
  if (input.tin_number) fd.set("tin_number", input.tin_number);
  if (input.legal_business_name) fd.set("legal_business_name", input.legal_business_name);
  if (input.business_email) fd.set("business_email", input.business_email);
  if (input.business_phone) fd.set("business_phone", input.business_phone);
  if (input.notes) fd.set("notes", input.notes);
  // Whoever invited this business, from /create-account?ref=CODE. Optional,
  // and the backend never fails a signup over a bad one.
  if (input.referral_code) fd.set("referral_code", input.referral_code);
  for (const service of input.services_needed ?? []) fd.append("services_needed", service);

  let res: Response;
  try {
    // No Content-Type header — the runtime sets the multipart boundary.
    res = await fetch(`${API_BASE}/v1/onboarding/signup`, { method: "POST", body: fd });
  } catch {
    throw new OnboardingApiError("Couldn't reach InfinityPay. Check your connection and try again.");
  }
  return parseEnvelope<MerchantSignupResult>(res);
}

export async function submitOnboardingAccount(
  input: OnboardingMerchantAccountInput,
): Promise<OnboardingMerchantAccountResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/onboarding/merchant-account`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeader()) },
      body: JSON.stringify(input),
    });
  } catch {
    throw new OnboardingApiError("Couldn't reach InfinityPay. Check your connection and try again.");
  }
  return parseEnvelope<OnboardingMerchantAccountResult>(res);
}

export async function uploadOnboardingDocument(documentType: DocumentType, file: File): Promise<OnboardingDocument> {
  const formData = new FormData();
  formData.append("document_type", documentType);
  formData.append("file", file);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/onboarding/documents`, {
      method: "POST",
      headers: await authHeader(),
      body: formData,
    });
  } catch {
    throw new OnboardingApiError("Couldn't reach InfinityPay. Check your connection and try again.");
  }
  return parseEnvelope<OnboardingDocument>(res);
}

// --- Super-admin review --------------------------------------------------

export async function listOnboardingSubmissions(): Promise<OnboardingSubmission[]> {
  try {
    const res = await fetch(`${API_BASE}/v1/admin/onboarding`, {
      headers: await authHeader(),
      cache: "no-store",
    });
    if (!res.ok) return [];
    return await parseEnvelope<OnboardingSubmission[]>(res);
  } catch {
    return [];
  }
}

export async function getOnboardingSubmission(id: string): Promise<OnboardingSubmission | null> {
  try {
    const res = await fetch(`${API_BASE}/v1/admin/onboarding/${id}`, {
      headers: await authHeader(),
      cache: "no-store",
    });
    if (!res.ok) return null;
    return await parseEnvelope<OnboardingSubmission>(res);
  } catch {
    return null;
  }
}

export async function approveOnboardingSubmission(id: string): Promise<OnboardingSubmission> {
  const res = await fetch(`${API_BASE}/v1/admin/onboarding/${id}/approve`, {
    method: "POST",
    headers: await authHeader(),
  });
  return parseEnvelope<OnboardingSubmission>(res);
}

export async function rejectOnboardingSubmission(id: string, note: string | null): Promise<OnboardingSubmission> {
  const res = await fetch(`${API_BASE}/v1/admin/onboarding/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeader()) },
    body: JSON.stringify({ review_note: note }),
  });
  return parseEnvelope<OnboardingSubmission>(res);
}

export async function requestMoreInfoOnboardingSubmission(id: string, note: string | null): Promise<OnboardingSubmission> {
  const res = await fetch(`${API_BASE}/v1/admin/onboarding/${id}/request-more-info`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeader()) },
    body: JSON.stringify({ review_note: note }),
  });
  return parseEnvelope<OnboardingSubmission>(res);
}
