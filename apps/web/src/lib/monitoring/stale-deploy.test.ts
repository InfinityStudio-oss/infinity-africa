import { describe, expect, it } from "vitest";

import { isStaleServerActionError } from "./stale-deploy";

/** The one error this app reports that is not a bug — a tab left open
 * across a deploy. It is filtered out of Sentry and given its own
 * message in the error boundary, so the matcher has to be right in both
 * directions: miss it and the noise comes back, over-match it and a real
 * failure is silently dropped on a platform that moves money. */
describe("isStaleServerActionError", () => {
  it("recognises the error Next.js actually throws", () => {
    // Verbatim from Sentry, 2026-10-14 11:33 — twelve hours after a deploy.
    const error = new Error(
      'Server Action "60c2688881cea118d4b972f15037b0a4d68e755aef" was not found on the server',
    );
    error.name = "UnrecognizedActionError";

    expect(isStaleServerActionError(error)).toBe(true);
  });

  it("matches on the message alone, since the name may not survive minification", () => {
    expect(
      isStaleServerActionError(
        new Error('Server Action "abc123" was not found on the server'),
      ),
    ).toBe(true);
  });

  it("matches on the name alone", () => {
    const error = new Error("something else entirely");
    error.name = "UnrecognizedActionError";
    expect(isStaleServerActionError(error)).toBe(true);
  });

  it.each([
    "Failed to fetch",
    "Cannot read properties of undefined (reading 'merchant_id')",
    "Insufficient balance for this withdrawal",
    "Server responded with 500",
    "NEXT_REDIRECT",
  ])("does not swallow a real failure: %s", (message) => {
    expect(isStaleServerActionError(new Error(message))).toBe(false);
  });

  it.each([null, undefined, 42, {}, []])("is false for a non-error value: %s", (value) => {
    expect(isStaleServerActionError(value)).toBe(false);
  });

  it("handles a bare string, which is what some rejections carry", () => {
    expect(isStaleServerActionError("UnrecognizedActionError: ...")).toBe(true);
    expect(isStaleServerActionError("withdrawal_restricted")).toBe(false);
  });
});
