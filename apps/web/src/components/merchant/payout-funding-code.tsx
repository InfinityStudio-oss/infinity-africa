"use client";

import { useState } from "react";

import type { WithdrawalOtpChallenge } from "@/lib/portal/api";

/**
 * The second factor on funding a payout wallet.
 *
 * Funding decides how much a leaked payout key can ever cost, so it
 * takes more than a live session. It used to demand Supabase step-up
 * MFA, which no merchant could reach — enrolment exists only for Super
 * Admins — so the dashboard told every merchant to complete a challenge
 * that did not exist for them and nobody could fund a wallet at all.
 *
 * This is the same emailed code they already use for withdrawals: no
 * enrolment, already familiar, and the same decision (how much money to
 * expose).
 *
 * Nothing has moved while this box is on screen. The transfer happens
 * only on a correct code, for the amount stored on the challenge.
 */
export function PayoutFundingCode({
  challenge,
  amountLabel,
  onConfirm,
  onCancel,
}: {
  challenge: WithdrawalOtpChallenge;
  amountLabel: string;
  onConfirm: (code: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError(null);
    setBusy(true);
    try {
      await onConfirm(code.trim());
    } catch (err) {
      // The backend's own message. "That code isn't valid" and "payouts
      // are paused" need different actions from the merchant.
      setError(err instanceof Error ? err.message : "That didn't work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    // A <div>, NOT a <form>. This renders inside the funding form, and
    // nested forms are invalid HTML: the browser drops the inner one, so
    // an inner type="submit" button submits the OUTER form instead. That
    // is not theoretical - it shipped, and every click of "Confirm and
    // move funds" silently re-ran "request a code". Three codes were
    // issued, none was ever verified, and the merchant was left staring
    // at a zero balance.
    <div className="rounded-lg border border-outline-variant bg-surface-container-low p-4 space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-on-background">Confirm with the code we emailed</h3>
        <p className="mt-1 text-sm text-on-surface-variant">
          We sent a 6-digit code to <span className="font-medium">{challenge.masked_email}</span>.
          Nothing has moved yet — entering it moves{" "}
          <span className="font-semibold">{amountLabel}</span> into your payout wallet.
        </p>
      </div>

      <div>
        <label htmlFor="funding-code" className="block text-sm font-medium mb-1">
          6-digit code
        </label>
        <input
          id="funding-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
          onKeyDown={(event) => {
            // Enter used to work for free via form submit. It has to be
            // explicit now, and it matters: typing a 6-digit code and
            // pressing Enter is what people do.
            if (event.key === "Enter" && code.length === 6 && !busy) {
              event.preventDefault();
              void submit();
            }
          }}
          className="w-40 px-3 py-2 rounded-lg border border-surface-container-highest bg-surface text-sm font-mono tracking-widest"
        />
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-700 font-medium">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={submit}
          disabled={busy || code.length !== 6}
          className="btn-brand px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {busy ? "Confirming…" : "Confirm and move funds"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-sm font-semibold text-on-surface-variant hover:underline"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
