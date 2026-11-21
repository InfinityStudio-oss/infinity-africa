"use client";

import { useState, useTransition } from "react";

import { updatePayoutTariffAction } from "@/lib/admin/live-actions";
import type { AdminPayoutTariff } from "@/lib/admin/types";

/**
 * The default payout fee, for every merchant without a negotiated rate.
 *
 * One rate for every destination — all mobile money networks, Selcom
 * Pesa and all banks. There is deliberately no per-destination
 * breakdown: Selcom's own operator codes have already changed once
 * under this product, and a tariff keyed on them would turn their next
 * change into a pricing bug.
 *
 * `tariff` is null when the row does not exist, which means the
 * migration has not been applied. Said plainly rather than shown as 0%,
 * because "payouts are free" and "the table is missing" must not look
 * the same on the screen that sets the price.
 */
export function PayoutTariffCard({ tariff }: { tariff: AdminPayoutTariff | null }) {
  const [editing, setEditing] = useState(false);
  const [percentage, setPercentage] = useState(tariff?.percentage_fee ?? "1");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!tariff) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
        <p className="font-semibold">No payout tariff is set up yet.</p>
        <p className="mt-1">
          The <code>payout_platform_pricing</code> migration has not been applied, so there is no
          default rate to charge. Payouts are not free — nothing can be priced at all until it is.
        </p>
      </div>
    );
  }

  function save() {
    setError(null);
    startTransition(async () => {
      const result = await updatePayoutTariffAction(
        percentage.trim(),
        tariff!.flat_fee,
        tariff!.version,
      );
      if (result.error) setError(result.error);
      else setEditing(false);
    });
  }

  return (
    <div className="rounded-xl border border-outline-variant bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-on-background">Standard payout tariff</h2>
          <p className="mt-1 text-sm text-on-surface-variant max-w-xl">
            Charged on every payout by any business without a negotiated rate of its own — the same
            rate for every mobile money network, Selcom Pesa and every bank.
          </p>
        </div>

        {editing ? (
          <div className="flex items-start gap-2">
            <div>
              <label htmlFor="tariff-pct" className="sr-only">
                Payout tariff percentage
              </label>
              <input
                id="tariff-pct"
                value={percentage}
                onChange={(event) => setPercentage(event.target.value)}
                className="w-24 rounded-lg border border-outline-variant bg-transparent px-3 py-2 text-sm text-on-surface"
              />
            </div>
            <button
              type="button"
              disabled={pending}
              onClick={save}
              className="rounded-lg bg-primary-container px-4 py-2 text-sm font-semibold text-on-primary disabled:cursor-wait"
            >
              {pending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="px-2 py-2 text-sm font-semibold text-on-surface-variant hover:underline"
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-2xl font-bold text-on-background">{tariff.percentage_fee}%</div>
              {Number(tariff.flat_fee) > 0 && (
                <div className="text-xs text-on-surface-variant">+ TZS {tariff.flat_fee} flat</div>
              )}
            </div>
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-lg border border-outline-variant px-4 py-2 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-low"
            >
              Change
            </button>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          {error}
        </p>
      )}

      <p className="mt-3 text-xs text-outline">
        A change applies to payouts created from now on. Payouts already queued or in flight keep the
        fee they were priced at.
      </p>
    </div>
  );
}
