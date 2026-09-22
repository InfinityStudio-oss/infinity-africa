import type { SupabaseClient } from "@supabase/supabase-js";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { establishRecoveryLinkSession as establishRecoveryLinkSessionImpl } from "./recovery-link";

function setUrl(hrefSuffix: string) {
  window.history.replaceState(null, "", `/dashboard/reset-password${hrefSuffix}`);
}

function fakeSupabase(overrides: Partial<Record<"exchangeCodeForSession" | "verifyOtp" | "setSession", ReturnType<typeof vi.fn>>> = {}) {
  return {
    auth: {
      exchangeCodeForSession: vi.fn().mockResolvedValue({ error: null }),
      verifyOtp: vi.fn().mockResolvedValue({ error: null }),
      setSession: vi.fn().mockResolvedValue({ error: null }),
      ...overrides,
    },
  };
}

// Only `auth.*` is ever touched by establishRecoveryLinkSession — the rest
// of the real SupabaseClient surface is irrelevant to this test, hence the
// cast; kept in one place so every call site below stays fully typed for
// its own assertions on `supabase.auth.*`.
function establishRecoveryLinkSession(
  supabase: ReturnType<typeof fakeSupabase>,
  options: Parameters<typeof establishRecoveryLinkSessionImpl>[1],
) {
  return establishRecoveryLinkSessionImpl(supabase as unknown as SupabaseClient, options);
}

describe("establishRecoveryLinkSession", () => {
  beforeEach(() => {
    setUrl("");
  });

  it("accepts a valid code link via exchangeCodeForSession", async () => {
    setUrl("?code=abc123");
    const supabase = fakeSupabase();

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["recovery"] });

    expect(supabase.auth.exchangeCodeForSession).toHaveBeenCalledWith("abc123");
    expect(result).toEqual({ status: "ready" });
  });

  it("accepts a valid token_hash recovery link via verifyOtp", async () => {
    setUrl("?token_hash=th_abc&type=recovery");
    const supabase = fakeSupabase();

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["recovery"] });

    expect(supabase.auth.verifyOtp).toHaveBeenCalledWith({ type: "recovery", token_hash: "th_abc" });
    expect(result).toEqual({ status: "ready" });
  });

  it("accepts a valid access_token/refresh_token hash link via setSession", async () => {
    setUrl("#access_token=at_abc&refresh_token=rt_abc&type=recovery");
    const supabase = fakeSupabase();

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["recovery"] });

    expect(supabase.auth.setSession).toHaveBeenCalledWith({ access_token: "at_abc", refresh_token: "rt_abc" });
    expect(result).toEqual({ status: "ready" });
  });

  it("rejects an expired/used link that Supabase redirected with an error", async () => {
    setUrl("#error=access_denied&error_description=Email+link+is+invalid+or+has+expired");
    const supabase = fakeSupabase();

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["recovery"] });

    expect(supabase.auth.exchangeCodeForSession).not.toHaveBeenCalled();
    expect(supabase.auth.verifyOtp).not.toHaveBeenCalled();
    expect(supabase.auth.setSession).not.toHaveBeenCalled();
    expect(result).toEqual({ status: "invalid", errorDescription: "Email link is invalid or has expired" });
  });

  it("rejects a reused link — Supabase's own error response for a used token", async () => {
    setUrl("#access_token=at_abc&refresh_token=rt_abc&type=recovery");
    const supabase = fakeSupabase({ setSession: vi.fn().mockResolvedValue({ error: { message: "Invalid Refresh Token" } }) });

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["recovery"] });

    expect(result).toEqual({ status: "invalid", errorDescription: "Invalid Refresh Token" });
  });

  it("rejects a URL with no recognizable token at all", async () => {
    setUrl("");
    const supabase = fakeSupabase();

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["recovery"] });

    expect(supabase.auth.exchangeCodeForSession).not.toHaveBeenCalled();
    expect(supabase.auth.verifyOtp).not.toHaveBeenCalled();
    expect(supabase.auth.setSession).not.toHaveBeenCalled();
    expect(result).toEqual({ status: "invalid", errorDescription: null });
  });

  it("scrubs the token from the URL after a successful exchange, so a reload can't replay it", async () => {
    setUrl("?code=abc123");
    const supabase = fakeSupabase();

    await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["recovery"] });

    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("");
  });

  it("does not accept a token_hash whose type isn't allowed for this page", async () => {
    // The reset-password page only allows "recovery" — an invite-typed
    // token_hash landing here must not be treated as valid just because a
    // token_hash is present.
    setUrl("?token_hash=th_abc&type=invite");
    const supabase = fakeSupabase();

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["recovery"] });

    expect(supabase.auth.verifyOtp).not.toHaveBeenCalled();
    expect(result.status).toBe("invalid");
  });

  it("accepts an invite-typed token_hash when the caller allows it (invite-accept page)", async () => {
    setUrl("?token_hash=th_abc&type=invite");
    const supabase = fakeSupabase();

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["invite", "recovery"] });

    expect(supabase.auth.verifyOtp).toHaveBeenCalledWith({ type: "invite", token_hash: "th_abc" });
    expect(result).toEqual({ status: "ready" });
  });

  it("accepts a recovery-typed token_hash on the invite-accept page (resend-invite reuses recovery)", async () => {
    setUrl("?token_hash=th_abc&type=recovery");
    const supabase = fakeSupabase();

    const result = await establishRecoveryLinkSession(supabase, { allowedOtpTypes: ["invite", "recovery"] });

    expect(supabase.auth.verifyOtp).toHaveBeenCalledWith({ type: "recovery", token_hash: "th_abc" });
    expect(result).toEqual({ status: "ready" });
  });
});
