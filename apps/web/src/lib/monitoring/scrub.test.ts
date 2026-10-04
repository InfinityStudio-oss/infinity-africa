import { describe, expect, it } from "vitest";

import { REDACTED, redactText, scrubEvent, scrubUrl } from "./scrub";

/**
 * The browser-side counterpart of
 * `apps/api/tests/test_monitoring_scrubber.py`. Same contract: each test
 * names something that must never reach Sentry, so a change that widens
 * what is sent fails here rather than in a dashboard.
 */

describe("redactText", () => {
  it.each([
    "sk_live_examplekey",
    "pk_test_9f2bc4d1e8a7b3c6",
    "re_AbCdEf123456789",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.dBjftJeZ4CVPmB92K27u",
    "Bearer abcdef1234567890",
  ])("redacts the secret %s", (secret) => {
    expect(redactText(`failed with ${secret}`)).not.toContain(secret);
  });

  it.each(["customer@example.com", "+255712345678", "0712345678", "255712345678"])(
    "redacts the personal identifier %s",
    (value) => {
      expect(redactText(`payer ${value} declined`)).not.toContain(value);
    },
  );

  it.each([
    ["OTP 482915 did not match", "482915"],
    ["Your one-time code is 4829", "4829"],
    ["verification code 123456 expired", "123456"],
    ["otp: 998877", "998877"],
  ])("redacts the one-time code in %s", (message, digits) => {
    expect(redactText(message)).not.toContain(digits);
  });

  it("does not eat amounts or status codes while doing it", () => {
    // The OTP rule is anchored on the label, never on bare digits. If it
    // ever starts matching numbers on their own this fails — a scrubber
    // that destroys every number makes error reports useless.
    const kept = redactText("amount 50000 status 502 attempt 3 ref ORD-991");
    expect(kept).toContain("50000");
    expect(kept).toContain("502");
    expect(kept).toContain("ORD-991");
  });

  it("keeps the rest of the message readable", () => {
    const out = redactText("Request to /v1/collections failed for +255712345678 with HTTP 502");
    expect(out).toContain("/v1/collections");
    expect(out).toContain("HTTP 502");
    expect(out).not.toContain("255712345678");
  });

  it("redacts a Supabase token, which lives in browser storage and so is the likeliest leak", () => {
    const token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhYmMiLCJyb2xlIjoiYXV0aCJ9.sig";
    expect(redactText(`storage: ${token}`)).toBe(`storage: ${REDACTED}`);
  });
});

describe("scrubUrl", () => {
  it("drops the query string, which is where reset tokens and ?email= arrive", () => {
    expect(scrubUrl("https://infinitypay.me/auth/callback?token_hash=pkce_abc123&type=recovery")).toBe(
      "https://infinitypay.me/auth/callback",
    );
  });

  it("drops the hash fragment, which is where Supabase puts access tokens", () => {
    expect(scrubUrl("https://infinitypay.me/dashboard/reset-password#access_token=eyJhbGciOi")).toBe(
      "https://infinitypay.me/dashboard/reset-password",
    );
  });

  it("keeps the path, because the path is the diagnosis", () => {
    expect(scrubUrl("https://infinitypay.me/pay/acme-water-bill")).toBe(
      "https://infinitypay.me/pay/acme-water-bill",
    );
  });
});

describe("scrubEvent", () => {
  it("drops the request body, cookies and headers", () => {
    const event = scrubEvent({
      request: {
        url: "https://infinitypay.me/pay/x?ref=1",
        data: { phone: "+255712345678", amount: "5000" },
        cookies: { "sb-access-token": "eyJhbGciOi" },
        headers: { Authorization: "Bearer sk_live_abcdefgh" },
        query_string: "ref=1",
      },
    })!;
    const request = event.request as Record<string, unknown>;
    expect(request.data).toBeUndefined();
    expect(request.cookies).toBeUndefined();
    expect(request.headers).toBeUndefined();
    expect(request.query_string).toBeUndefined();
    expect(request.url).toBe("https://infinitypay.me/pay/x");
  });

  it("scrubs breadcrumbs, which otherwise carry every fetch URL the session made", () => {
    const event = scrubEvent({
      breadcrumbs: [
        {
          category: "fetch",
          data: { url: "https://api.infinitypay.me/v1/collections?phone=255712345678" },
        },
        { category: "navigation", message: "signed in as owner@merchant.co.tz" },
      ],
    })!;
    expect(JSON.stringify(event)).not.toContain("255712345678");
    expect(JSON.stringify(event)).not.toContain("owner@merchant.co.tz");
  });

  it("reduces the user object to an id and nothing else", () => {
    const event = scrubEvent({
      user: { id: "8f14e45f-ea2b-4c1b-9c3d-2a1b7e5f6d4c", email: "ceo@infinitypay.me", ip_address: "41.86.1.2" },
    })!;
    expect(event.user).toEqual({ id: "8f14e45f-ea2b-4c1b-9c3d-2a1b7e5f6d4c" });
  });

  it("drops the value of any sensitive key, whatever it looks like", () => {
    const event = scrubEvent({
      extra: {
        webhook_secret: "1234",
        customer_phone: "x",
        api_key: "short",
        otp: "482915",
        verification_code: "1234",
        other: "kept",
      },
    })!;
    const extra = event.extra as Record<string, unknown>;
    expect(extra.webhook_secret).toBe(REDACTED);
    expect(extra.customer_phone).toBe(REDACTED);
    expect(extra.api_key).toBe(REDACTED);
    expect(extra.otp).toBe(REDACTED);
    expect(extra.verification_code).toBe(REDACTED);
    expect(extra.other).toBe("kept");
  });

  it("keeps the parts of an event that make it actionable", () => {
    const event = scrubEvent({
      level: "error",
      exception: { values: [{ type: "TypeError", value: "cannot read property of undefined" }] },
      tags: { route: "/dashboard/overview" },
    })!;
    expect(event.level).toBe("error");
    expect(JSON.stringify(event.exception)).toContain("TypeError");
    expect((event.tags as Record<string, string>).route).toBe("/dashboard/overview");
  });

  it("terminates on a deeply nested payload rather than hanging", () => {
    type Nested = { next?: Nested };
    const root: Nested = {};
    let cursor = root;
    for (let i = 0; i < 200; i += 1) {
      cursor.next = {};
      cursor = cursor.next;
    }
    expect(scrubEvent({ extra: root })).not.toBeNull();
  });

  it("drops the event rather than sending it when scrubbing fails", () => {
    // Returning the event on failure would send an unscrubbed payload,
    // which is the one outcome worse than losing the report.
    const hostile = {
      get request() {
        throw new Error("boom");
      },
    };
    expect(scrubEvent(hostile as unknown as Record<string, unknown>)).toBeNull();
  });
});
