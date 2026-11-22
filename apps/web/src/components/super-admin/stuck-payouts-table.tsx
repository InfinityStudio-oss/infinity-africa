"use client";

import { useState, useTransition } from "react";

import { tdClass, thClass } from "@/components/portal/card";
import { formatDateTime } from "@/lib/format";
import { releasePayoutAction } from "@/lib/admin/live-actions";
import type { AdminPayoutRow } from "@/lib/admin/types";

/**
 * Payouts parked in reconciliation — money held, with no answer from
 * the provider — and the one control that frees it.
 *
 * Releasing is the most dangerous thing on this screen. It hands the
 * merchant back funds on a human's judgement that the provider did not
 * pay; if that judgement is wrong, the money went out AND went back,
 * and the platform covers the difference. So:
 *
 *  - It asks for a written reason, which is stored and audited. That
 *    sentence is the only record of the judgement.
 *  - A payout the provider ACKNOWLEDGED offers no button at all. The
 *    backend refuses those outright, and a button that exists only to
 *    produce an error teaches an operator to click through errors.
 */

function money(value: string, currency: string): string {
  return `${currency} ${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2 }).format(Number(value))}`;
}

export function StuckPayoutsTable({ rows }: { rows: AdminPayoutRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-outline-variant bg-surface p-6 text-center">
        <p className="text-sm text-on-surface-variant">
          No payout is waiting on a decision. Anything parked in reconciliation — money held with
          no answer from the provider — would appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-outline-variant bg-surface overflow-x-auto">
      <table className="w-full text-left min-w-[980px]">
        <thead>
          <tr className="text-on-surface-variant text-xs font-semibold">
            <th className={thClass}>Business</th>
            <th className={thClass}>Held</th>
            <th className={thClass}>Why it is stuck</th>
            <th className={thClass}>Tried</th>
            <th className={thClass}>Created</th>
            <th className={`${thClass} text-right`}>Funds</th>
          </tr>
        </thead>
        <tbody className="text-sm">
          {rows.map((row) => (
            <StuckRow key={row.id} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StuckRow({ row }: { row: AdminPayoutRow }) {
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const name = row.business_name ?? row.merchant_code ?? row.merchant_id;

  function release() {
    setError(null);
    startTransition(async () => {
      const result = await releasePayoutAction(row.id, reason.trim());
      if (result.error) setError(result.error);
      else setConfirming(false);
    });
  }

  return (
    <tr className="border-t border-surface-container-highest align-top">
      <td className={tdClass}>
        <div className="font-medium text-on-background">{name}</div>
        <div className="font-mono text-[11px] text-on-surface-variant">{row.environment}</div>
        {error && (
          <p role="alert" className="text-[11px] text-red-700 mt-1 max-w-[16rem]">
            {error}
          </p>
        )}
      </td>

      <td className={`${tdClass} font-mono text-xs text-on-background`}>
        {money(row.total_debit, row.currency)}
      </td>

      <td className={`${tdClass} text-xs text-on-surface-variant max-w-[20rem]`}>
        <div className="font-mono">{row.failure_code ?? "—"}</div>
        {row.failure_reason && <p className="mt-0.5">{row.failure_reason}</p>}
      </td>

      <td className={`${tdClass} text-xs text-on-surface-variant`}>{row.dispatch_attempts}×</td>

      <td className={`${tdClass} text-xs text-on-surface-variant`}>{formatDateTime(row.created_at)}</td>

      <td className={`${tdClass} text-right`}>
        {row.provider_acknowledged ? (
          // No button. The provider took this one, so it may have been
          // paid, and it has to be settled by asking them.
          <span className="text-[11px] text-amber-700 max-w-[13rem] inline-block">
            The provider acknowledged this payout. Settle it with them — the funds cannot be
            released here.
          </span>
        ) : confirming ? (
          <div className="space-y-1.5 max-w-[17rem] ml-auto text-left">
            <p className="text-[11px] text-red-800">
              Return {money(row.total_debit, row.currency)} to <strong>{name}</strong>. Only do
              this if you know the provider did not pay.
            </p>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              aria-label={`Reason for releasing the payout for ${name}`}
              placeholder="How do you know? (required)"
              className="w-full rounded border border-outline-variant bg-transparent px-2 py-1 text-xs text-on-surface"
            />
            <div className="flex gap-2">
              <button
                type="button"
                disabled={pending || reason.trim().length < 10}
                onClick={release}
                className="rounded bg-red-700 px-2.5 py-1 text-xs font-semibold text-white hover:bg-red-800 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {pending ? "Releasing…" : "Release funds"}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="text-xs font-semibold text-on-surface-variant hover:underline"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="text-xs font-semibold text-primary-container hover:underline"
          >
            Release funds
          </button>
        )}
      </td>
    </tr>
  );
}
