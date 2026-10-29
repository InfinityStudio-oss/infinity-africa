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
    expect(location.searchParams.get("notice")).toMatch(/didn't work/i);
  });

  it("does not tell a merchant they are verified when redeeming just failed", async () => {
    // The notice used to say "Your email is verified. Sign in to
    // continue." On a genuine failure that is false, and it closes a
    // loop: the merchant is told they are verified, signs in, and the
    // login tells them their email still needs verifying. Neither screen
    // offers a way out.
    verifyOtp.mockResolvedValue({ error: { message: "Token has expired or is invalid" } });

    const res = await callGet(
      "https://infinitypay.me/auth/callback?token_hash=expired&type=magiclink",
    );

    const notice = new URL(res.headers.get("location")!).searchParams.get("notice")!;
    expect(notice).not.toMatch(/your email is verified/i);
    expect(notice).toMatch(/expired|already been used/i);
    // and it says what to do next, on the page it is sending them to
    expect(notice).toMatch(/sign(ing)? in/i);
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
