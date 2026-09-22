import { beforeEach, describe, expect, it, vi } from "vitest";

const exchangeCodeForSession = vi.fn();
const verifyOtp = vi.fn();

vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({ auth: { exchangeCodeForSession, verifyOtp } }),
}));

async function callGet(url: string) {
  const { GET } = await import("./route");
  return GET(new Request(url));
}

beforeEach(() => {
  vi.clearAllMocks();
  exchangeCodeForSession.mockResolvedValue({ error: null });
  verifyOtp.mockResolvedValue({ error: null });
});

describe("GET /auth/callback", () => {
  it("exchanges a PKCE code and forwards the verified merchant to /onboarding", async () => {
    const res = await callGet("https://infinitypay.me/auth/callback?code=abc123&next=/onboarding");

    expect(exchangeCodeForSession).toHaveBeenCalledWith("abc123");
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("https://infinitypay.me/onboarding");
  });

  it("verifies a token_hash / type=signup link (cross-device style)", async () => {
    const res = await callGet(
      "https://infinitypay.me/auth/callback?token_hash=xyz&type=signup",
    );

    expect(verifyOtp).toHaveBeenCalledWith({ type: "signup", token_hash: "xyz" });
    expect(res.headers.get("location")).toBe("https://infinitypay.me/onboarding");
  });

  it("sends a failed exchange to /dashboard/login with a plain-language notice, never a 400", async () => {
    exchangeCodeForSession.mockResolvedValue({ error: { message: "code challenge does not match" } });

    const res = await callGet("https://infinitypay.me/auth/callback?code=stale");

    expect(res.status).toBe(307);
    const location = new URL(res.headers.get("location")!);
    expect(location.pathname).toBe("/dashboard/login");
    expect(location.searchParams.get("notice")).toMatch(/verified/i);
  });

  it("treats a link opened with no token as 'verified — please sign in', not an error page", async () => {
    const res = await callGet("https://infinitypay.me/auth/callback");

    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    const location = new URL(res.headers.get("location")!);
    expect(location.pathname).toBe("/dashboard/login");
  });

  it("routes an error_description straight to login without touching Supabase", async () => {
    const res = await callGet(
      "https://infinitypay.me/auth/callback?error_description=Email+link+is+invalid+or+has+expired",
    );

    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    expect(verifyOtp).not.toHaveBeenCalled();
    expect(new URL(res.headers.get("location")!).pathname).toBe("/dashboard/login");
  });

  it("ignores an off-site `next` (open-redirect guard) and falls back to /onboarding", async () => {
    const res = await callGet(
      "https://infinitypay.me/auth/callback?code=ok&next=https://evil.example.com",
    );

    expect(res.headers.get("location")).toBe("https://infinitypay.me/onboarding");
  });

  it("does not re-run the exchange when the same request is handled once (single consume)", async () => {
    await callGet("https://infinitypay.me/auth/callback?code=abc123");
    expect(exchangeCodeForSession).toHaveBeenCalledTimes(1);
  });
});
