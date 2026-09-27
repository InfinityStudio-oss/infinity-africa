"use client";

import {
  DESTINATION_CODE_LABELS,
  DISBURSEMENT_METHOD_LABELS,
  DisbursementMethod,
} from "@infinity/shared";

import { Icon } from "@/components/portal/icon";
import { formatCurrency } from "@/lib/format";

/**
 * The step between filling in a withdrawal and asking for a verification
 * code: exactly what is about to be submitted, shown once, before anything
 * leaves the browser.
 *
 * Nothing has been requested at this point — no withdrawal, no code, no
 * server call at all — so Back is offered plainly rather than behind a
 * confirmation.
 *
 * Two things are deliberately absent. **Charges**, because a merchant
 * withdrawal is not charged and a "TZS 0.00 fee" line invites the question
 * of when it might not be. And **the recipient's name**: no provider name
 * lookup exists, so the only name available would be one the merchant
 * typed themselves, which confirms nothing. Showing a typed name back as
 * if it were verified is worse than showing none, because it reads like
 * the destination was checked.
 */
export function WithdrawalReview({
  method,
  destinationCode,
  destinationIdentifier,
  amount,
  balance,
  busy,
  onBack,
  onConfirm,
  /** Present only if a real, provider-resolved account holder is ever
   * available. Never a merchant-typed value. */
  resolvedRecipientName = null,
}: {
  method: DisbursementMethod;
  destinationCode: string;
  destinationIdentifier: string;
  amount: string;
  balance: string;
  busy: boolean;
  onBack: () => void;
  onConfirm: () => void;
  resolvedRecipientName?: string | null;
}) {
  const methodLabel = DISBURSEMENT_METHOD_LABELS[method];
  const destinationLabel =
    (DESTINATION_CODE_LABELS as Record<string, string | undefined>)[destinationCode] ?? destinationCode;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Review withdrawal"
    >
      <div className="w-full max-w-md rounded-xl bg-surface p-6 shadow-ambient max-h-[90vh] overflow-y-auto">
        <h3 className="text-xl font-semibold text-on-background">Review your withdrawal details</h3>
        <p className="mt-1.5 text-sm text-on-surface-variant">
          We&apos;ll send a verification code to your email before submitting this request.
        </p>

        <dl className="mt-5 space-y-3 rounded-lg bg-surface-container-low px-4 py-4 text-sm">
          <Row
            label="Recipient name"
            value={resolvedRecipientName}
            fallback="Name not available"
          />
          <Row label="Withdraw to" value={methodLabel} />
          {/* Only when it says something the method line did not. For
              Selcom Pesa the two are the same name, and repeating it reads
              as though there were two different things to check. */}
          {destinationLabel !== methodLabel ? (
            <Row label="Destination" value={destinationLabel} />
          ) : null}
          <Row
            label={method === DisbursementMethod.BANK_ACCOUNT ? "Account number" : "Phone number"}
            value={destinationIdentifier}
            mono
          />
          <div className="flex items-start justify-between gap-4 border-t border-surface-container-highest pt-3">
            <dt className="text-on-surface-variant">Amount</dt>
            <dd className="text-right text-lg font-semibold text-on-background">
              {formatCurrency(amount, "TZS")}
            </dd>
          </div>
          <div className="flex items-start justify-between gap-4">
            <dt className="text-on-surface-variant">Available balance</dt>
            <dd className="text-right font-medium text-on-surface">{formatCurrency(balance, "TZS")}</dd>
          </div>
        </dl>

        <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">
          <button
            type="button"
            onClick={onBack}
            disabled={busy}
            className="text-sm font-medium text-on-surface-variant hover:underline disabled:opacity-60"
          >
            Back
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="flex items-center justify-center gap-2 rounded-lg bg-primary-container px-6 py-3 text-sm font-medium text-on-primary hover:opacity-90 disabled:opacity-60"
          >
            <Icon name="mail" className="text-[20px]" />
            {busy ? "Sending code…" : "Send Verification Code"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  fallback,
  mono = false,
}: {
  label: string;
  value: string | null | undefined;
  fallback?: string;
  mono?: boolean;
}) {
  const shown = value || fallback;
  if (!shown) return null;
  const missing = !value && Boolean(fallback);
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="text-on-surface-variant">{label}</dt>
      <dd
        className={[
          "text-right",
          mono ? "font-mono text-sm" : "",
          missing ? "text-on-surface-variant italic" : "font-medium text-on-background",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {shown}
      </dd>
    </div>
  );
}
