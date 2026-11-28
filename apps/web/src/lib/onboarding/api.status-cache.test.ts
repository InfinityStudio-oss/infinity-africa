/**
 * getOnboardingStatus is on the critical path of every portal page — the
 * portal layout and four pages await it before rendering anything — and
 * it goes to Railway, which queries Supabase. Clicking Overview ->
 * Withdrawals -> Invoices used to cost three identical round trips.
 *
 * These tests hold the short reuse window in place, and hold its two
 * safety properties in place with it:
 *
 *   1. a FAILED answer is never stored (one bad second must not become
 *      ten seconds of a verified merchant bounced to /onboarding)
 *   2. one merchant can never read another's entry
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

let currentToken: string | null = "merchant-a-token";
vi.mock("@/lib/supabase/session", () => ({
  getAccessToken: async () => currentToken,
}));

const VERIFIED = {
  account_status: "VERIFIED",
  merchant_status: "active",
  next_path: "/dashboard/overview",
};

function respondWith(payload: unknown, ok = true) {
  // The parameters are declared, unused, so the recorded call is a
  // two-element tuple and the Authorization assertions below can read
  // calls[0][1]. Without them `next build`'s type check rejects the
  // index on a zero-length tuple — and it is the only check that does.
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => ({
    ok,
    json: async () => ({ success: ok, data: payload }),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function freshModule() {
  vi.resetModules();
  return import("./api");
}

beforeEach(() => {
  vi.useFakeTimers();
  currentToken = "merchant-a-token";
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the onboarding status reuse window", () => {
  it("asks the API once for repeated page loads in the same few seconds", async () => {
    const { getOnboardingStatus, __clearOnboardingStatusCache } = await freshModule();
    __clearOnboardingStatusCache();
    const fetchMock = respondWith(VERIFIED);

    const first = await getOnboardingStatus();
    vi.advanceTimersByTime(3_000);
    const second = await getOnboardingStatus();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(second).toEqual(first);
  });

  it("asks again once the window has passed", async () => {
    const { getOnboardingStatus, __clearOnboardingStatusCache } = await freshModule();
    __clearOnboardingStatusCache();
    const fetchMock = respondWith(VERIFIED);

    await getOnboardingStatus();
    // Longer than STATUS_TTL_MS. A suspension or an approval has to reach
    // the portal, and this is the delay that decides how fast it does.
    vi.advanceTimersByTime(11_000);
    await getOnboardingStatus();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never stores a failure", async () => {
    const { getOnboardingStatus, __clearOnboardingStatusCache } = await freshModule();
    __clearOnboardingStatusCache();
    const fetchMock = respondWith(null, false);

    expect(await getOnboardingStatus()).toBeNull();
    expect(await getOnboardingStatus()).toBeNull();

    // Both asked. Caching the null would have sent a verified merchant to
    // /onboarding for the rest of the window over one bad response.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("recovers on the very next call after a failure", async () => {
    const { getOnboardingStatus, __clearOnboardingStatusCache } = await freshModule();
    __clearOnboardingStatusCache();
    respondWith(null, false);
    expect(await getOnboardingStatus()).toBeNull();

    respondWith(VERIFIED);
    expect(await getOnboardingStatus()).toEqual(VERIFIED);
  });

  it("does not let one merchant read another's status", async () => {
    const { getOnboardingStatus, __clearOnboardingStatusCache } = await freshModule();
    __clearOnboardingStatusCache();

    respondWith(VERIFIED);
    expect(await getOnboardingStatus()).toEqual(VERIFIED);

    // A different session is a different token is a different key.
    currentToken = "merchant-b-token";
    const pending = { ...VERIFIED, account_status: "PENDING_VERIFICATION" };
    const fetchMock = respondWith(pending);

    expect(await getOnboardingStatus()).toEqual(pending);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("asks every time when there is no session to key on", async () => {
    const { getOnboardingStatus, __clearOnboardingStatusCache } = await freshModule();
    __clearOnboardingStatusCache();
    currentToken = null;
    const fetchMock = respondWith(VERIFIED);

    await getOnboardingStatus();
    await getOnboardingStatus();

    // No token, no key — and an anonymous entry shared between callers is
    // exactly the leak this must not have.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("still sends the caller's own token on the request", async () => {
    const { getOnboardingStatus, __clearOnboardingStatusCache } = await freshModule();
    __clearOnboardingStatusCache();
    const fetchMock = respondWith(VERIFIED);

    await getOnboardingStatus();

    const init = fetchMock.mock.calls[0]?.[1];
    expect((init?.headers as Record<string, string>)?.Authorization).toBe("Bearer merchant-a-token");
  });

  it("uses an explicitly passed token, for the moment right after sign-in", async () => {
    const { getOnboardingStatus, __clearOnboardingStatusCache } = await freshModule();
    __clearOnboardingStatusCache();
    const fetchMock = respondWith(VERIFIED);

    // The cookies for this session have not been written yet, so
    // getAccessToken() would race them — callers pass the token instead.
    await getOnboardingStatus("just-signed-in-token");

    const init = fetchMock.mock.calls[0]?.[1];
    expect((init?.headers as Record<string, string>)?.Authorization).toBe("Bearer just-signed-in-token");
  });
});
