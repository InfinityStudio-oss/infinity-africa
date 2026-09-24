"use client";

import { useEffect, useRef, useState } from "react";

import { resendWithdrawalOtp, verifyWithdrawalOtp, type WithdrawalOtpChallenge } from "@/lib/portal/api";
import type { Disbursement } from "@/lib/portal/types";

/**
 * The verification step between filling in a withdrawal and it being
 * submitted for approval.
 *
 * Nothing exists server-side until this succeeds — no withdrawal row, no
 * reservation, no provider call. Cancelling is therefore genuinely free,
 * which is why Cancel is offered plainly rather than hidden behind a
 * confirmation.
 */
export function WithdrawalOtpModal({
  challenge,
  onVerified,
  onCancel,
}: {
  challenge: WithdrawalOtpChallenge;
  onVerified: (disbursement: Disbursement) => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(challenge.resend_cooldown_seconds);
  const [current, setCurrent] = useState(challenge);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Counts the resend cooldown down to zero. The backend enforces it too —
  // this only stops the merchant pressing a button that would be refused.
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  async function handleVerify(event: React.FormEvent) {
    event.preventDefault();
    if (code.length !== 6 || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      onVerified(await verifyWithdrawalOtp(current.challenge_id, code));
    } catch (err) {
      // The backend returns one deliberately generic message for every
      // failure (wrong, expired, locked) — shown as-is rather than
      // second-guessed, so the UI never reveals more than the API chose to.
      setError((err as Error).message || "That code isn't valid. Request a new one and try again.");
      setCode("");
      inputRef.current?.focus();
      setBusy(false);
    }
  }

  async function handleResend() {
    if (cooldown > 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const refreshed = await resendWithdrawalOtp(current.challenge_id);
      setCurrent(refreshed);
      setCooldown(refreshed.resend_cooldown_seconds);
      setCode("");
      setNotice("We've sent a new code. The previous one no longer works.");
      inputRef.current?.focus();
    } catch (err) {
      setError((err as Error).message || "Couldn't send a new code. Try again shortly.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="withdrawal-otp-title"
    >
      <div className="w-full max-w-md rounded-t-2xl bg-surface p-6 shadow-lg sm:rounded-2xl sm:p-8">
        <h2 id="withdrawal-otp-title" className="text-lg font-bold text-on-surface sm:text-xl">
          Enter the 6-digit code
        </h2>
        <p className="mt-2 text-sm text-on-surface-variant">
          We sent it to <span className="font-semibold text-on-surface">{current.masked_email}</span>. It expires in
          a few minutes.
        </p>

        <form onSubmit={handleVerify} className="mt-6">
          <label htmlFor="withdrawal-otp" className="sr-only">
            6-digit verification code
          </label>
          <input
            id="withdrawal-otp"
            ref={inputRef}
            value={code}
            // inputMode numeric brings up the digit keypad on mobile;
            // one-time-code lets iOS and Android offer the code straight
            // from the notification.
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="000000"
            onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
            className="w-full rounded-lg border border-outline-variant bg-surface px-4 py-3 text-center text-2xl font-semibold tracking-[0.4em] text-on-surface focus:border-primary-container focus:outline-none focus:ring-2 focus:ring-primary-container/40"
          />

          {error && (
            <p role="alert" className="mt-3 rounded-lg bg-error/10 px-3 py-2 text-sm font-medium text-error">
              {error}
            </p>
          )}
          {notice && !error && (
            <p className="mt-3 rounded-lg bg-primary-container/10 px-3 py-2 text-sm text-on-surface">{notice}</p>
          )}

          <button
            type="submit"
            disabled={code.length !== 6 || busy}
            className="mt-5 w-full rounded-lg bg-primary-container px-4 py-3 text-sm font-semibold text-on-primary transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? "Verifying…" : "Verify and submit"}
          </button>
        </form>

        <div className="mt-4 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={handleResend}
            disabled={cooldown > 0 || busy}
            className="text-sm font-semibold text-primary-container hover:underline disabled:cursor-not-allowed disabled:text-outline disabled:no-underline"
          >
            {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="text-sm font-medium text-on-surface-variant hover:underline"
          >
            Cancel
          </button>
        </div>

        <p className="mt-5 text-xs text-on-surface-variant">
          Entering this code submits the request for approval. It does not release any funds — every withdrawal is
          reviewed by InfinityPay before payment.
        </p>
      </div>
    </div>
  );
}
