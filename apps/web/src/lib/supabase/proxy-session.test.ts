/**
 * updateSession() runs on every request the proxy matches. What it does
 * there — and, just as importantly, what it does NOT do — decides the
 * latency floor of the whole portal.
 *
 * It calls getSession(), not getUser(). getUser() revalidates the JWT
 * over the network every single time; getSession() reads the cookie and
 * only goes to the network when the token is close to expiring, which is
 * when it refreshes it. Refreshing that cookie is the only reason this
 * function exists, because a Server Component cannot set cookies.
 *
 * Nothing is weakened by that: the result was always discarded here, and
 * every page still proves who the caller is with its own getUser() in
 * lib/supabase/session.ts. Next's own guidance agrees — see
 * node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md:
 * "Proxy is _not_ intended for slow data fetching ... it should not be
 * used as a full session management or authorization solution."
 *
 * These tests exist because the obvious "tidy-up" is to put getUser()
 * back, and because a change that skipped the refresh would log every
 * merchant out mid-session with nothing failing loudly.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSession = vi.hoisted(() => vi.fn(async () => ({ data: { session: null }, error: null })));
const getUser = vi.hoisted(() => vi.fn(async () => ({ data: { user: null }, error: null })));
const createServerClient = vi.hoisted(() => vi.fn());

vi.mock("@supabase/ssr", () => ({ createServerClient }));

const { updateSession } = await import("./proxy-session");
const { NextRequest } = await import("next/server");

/** The cookie writes the client asks for, as @supabase/ssr would after a
 * token refresh. */
let cookiesToSet: { name: string; value: string; options: Record<string, unknown> }[] = [];

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://project.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key-for-tests";
  getSession.mockClear();
  getUser.mockClear();
  createServerClient.mockClear();
  cookiesToSet = [];

  createServerClient.mockImplementation((_url: string, _key: string, options: never) => {
    const { cookies } = options as unknown as {
      cookies: { getAll: () => unknown; setAll: (c: typeof cookiesToSet) => void };
    };
    return {
      auth: {
        getSession: async () => {
          // A real refresh writes the new session back through setAll;
          // this stands in for that so the propagation is exercised.
          if (cookiesToSet.length) cookies.setAll(cookiesToSet);
          return getSession();
        },
        getUser,
      },
    };
  });
});

function request(path = "/dashboard/overview") {
  return new NextRequest(new URL(`https://infinitypay.me${path}`));
}

describe("what the proxy does on every request", () => {
  it("reads the session instead of revalidating it over the network", async () => {
    await updateSession(request());

    expect(getSession).toHaveBeenCalledTimes(1);
    // The duplicate revalidation. The page still does this one; the
    // proxy doing it too was a second intercontinental round trip on
    // every page load, and its answer was thrown away.
    expect(getUser).not.toHaveBeenCalled();
  });

  it("still writes a refreshed cookie back to the browser", async () => {
    cookiesToSet = [{ name: "sb-access-token", value: "refreshed", options: { path: "/" } }];

    const response = await updateSession(request());

    expect(response.cookies.get("sb-access-token")?.value).toBe("refreshed");
  });

  it("does nothing at all when Supabase is not configured", async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = "http://localhost:54321";

    await updateSession(request());

    expect(createServerClient).not.toHaveBeenCalled();
    expect(getSession).not.toHaveBeenCalled();
  });

  it("lets the request through when Supabase throws", async () => {
    getSession.mockRejectedValueOnce(new Error("unreachable"));

    // Fails open, deliberately: a Supabase blip must not take the whole
    // site down, and this makes no authorization decision to get wrong.
    const response = await updateSession(request());

    expect(response.status).toBe(200);
  });

});
