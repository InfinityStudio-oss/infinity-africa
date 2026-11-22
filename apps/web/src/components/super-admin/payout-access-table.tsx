"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { formatDateTime } from "@/lib/format";
import {
  dismissPayoutRequestAction,
  setPayoutFeeAction,
  setPayoutLiveAction,
  setPayoutPauseAction,
  setPayoutSandboxAction,
} from "@/lib/admin/live-actions";
import type { AdminPayoutAccessRow } from "@/lib/admin/types";

/**
 * Super Admin → Payouts.
 *
 * Who may send money through the Disbursement API, within what limits,
 * at what price. Every control here changes what a machine is allowed
 * to do with real money and nobody approving each request, so the
 * screen is built to make the weight of each one visible rather than
 * uniform:
 *
 *  - Sandbox is one click. It spends play money.
 *  - Live asks for confirmation naming the merchant, because it is the
 *    only control on this page that can cost real money, and because it
 *    was previously impossible through any screen at all - people did it
 *    by editing the database, where nothing checked and nothing was
 *    recorded.
 *  - Pause requires a reason. A pause nobody explained is one the next
 *    operator cannot safely lift.
 *
 * Fees read "Standard (tariff)" when the merchant has no negotiated
 * rate, never the tariff's number: an operator seeing "1%" in a
 * merchant's row would reasonably read it as this merchant's own deal
 * and keep it while changing the tariff for everyone else.
 */

/** Asked, and still waiting on an answer. */
function waiting(row: AdminPayoutAccessRow): boolean {
  return Boolean(row.access_requested_at) && !row.sandbox_enabled && !row.live_enabled;
}

function money(value: string | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 2 }).format(Number(value));
}

export function PayoutAccessTable({ rows }: { rows: AdminPayoutAccessRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-outline-variant bg-surface p-8 text-center">
        <p className="text-sm text-on-surface-variant">
          No business has payout settings yet. A business appears here once it has been given a
          settings row — that is not itself a grant, it is what makes them manageable.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-outline-variant bg-surface overflow-x-auto">
      <table className="w-full text-left min-w-[1100px]">
        <thead>
          <tr className="text-on-surface-variant text-xs font-semibold">
            <th className={thClass}>Business</th>
            <th className={thClass}>Sandbox</th>
            <th className={thClass}>Live</th>
            <th className={thClass}>Payout wallet</th>
            <th className={thClass}>Limits</th>
            <th className={thClass}>Fee</th>
            <th className={thClass}>State</th>
            <th className={`${thClass} text-right`}>Changed</th>
          </tr>
        </thead>
        <tbody className="text-sm">
          {/* Anyone waiting goes first. A request nobody can see is the
              same as no request, and this list grows with every merchant
              ever granted access. */}
          {[...rows]
            .sort((a, b) => Number(waiting(b)) - Number(waiting(a)))
            .map((row) => (
              <PayoutRow key={row.merchant_id} row={row} />
            ))}
        </tbody>
      </table>
    </div>
  );
}

function PayoutRow({ row }: { row: AdminPayoutAccessRow }) {
  const [error, setError] = useState<string | null>(null);
  const [confirmingLive, setConfirmingLive] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [reason, setReason] = useState("");
  const [editingFee, setEditingFee] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [dismissReason, setDismissReason] = useState("");
  const [feePercent, setFeePercent] = useState(row.fee_percentage ?? "");
  const [pending, startTransition] = useTransition();

  const name = row.business_name ?? row.merchant_code ?? row.merchant_id;

  function run(work: () => Promise<{ error: string | null }>, done?: () => void) {
    setError(null);
    startTransition(async () => {
      const result = await work();
      if (result.error) setError(result.error);
      else done?.();
    });
  }

  return (
    <tr className="border-t border-surface-container-highest align-top">
      <td className={tdClass}>
        <div className="font-medium text-on-background">{name}</div>
        {row.merchant_code && (
          <div className="font-mono text-xs text-on-surface-variant">{row.merchant_code}</div>
        )}
        {/* Someone asked and is waiting. Shown only while nothing is
            granted: once they are switched on the request is history,
            and leaving the badge up would make the queue unreadable. */}
        {waiting(row) &&
          (dismissing ? (
            <div className="mt-1.5 space-y-1.5 max-w-[15rem]">
              <input
                value={dismissReason}
                onChange={(event) => setDismissReason(event.target.value)}
                aria-label={`Reason for dismissing the request from ${name}`}
                placeholder="Why? (recorded)"
                className="w-full rounded border border-outline-variant bg-transparent px-2 py-1 text-xs text-on-surface"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={pending || dismissReason.trim().length < 5}
                  onClick={() =>
                    run(
                      () =>
                        dismissPayoutRequestAction(row.merchant_id, row.version, dismissReason.trim()),
                      () => {
                        setDismissing(false);
                        setDismissReason("");
                      },
                    )
                  }
                  className="rounded bg-surface-container-highest px-2 py-1 text-xs font-semibold text-on-surface disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Dismiss
                </button>
                <button
                  type="button"
                  onClick={() => setDismissing(false)}
                  className="text-xs font-semibold text-on-surface-variant hover:underline"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="mt-1 flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                Requested {formatDateTime(row.access_requested_at!)}
              </span>
              {/* Takes it out of the queue. Not a refusal the merchant
                  sees and not a block - they keep the same not-enabled
                  page and can ask again, which re-stamps the row. */}
              <button
                type="button"
                onClick={() => setDismissing(true)}
                className="text-[11px] font-semibold text-on-surface-variant hover:underline"
              >
                Dismiss
              </button>
            </div>
          ))}
        {error && (
          <p role="alert" className="text-[11px] text-red-700 mt-1 max-w-[16rem]">
            {error}
          </p>
        )}
      </td>

      <td className={tdClass}>
        <button
          type="button"
          role="switch"
          aria-checked={row.sandbox_enabled}
          aria-label={`Sandbox payouts for ${name}`}
          disabled={pending}
          onClick={() => run(() => setPayoutSandboxAction(row.merchant_id, !row.sandbox_enabled, row.version))}
          title={
            row.sandbox_enabled
              ? "Click to switch sandbox payouts off"
              : "Click to switch sandbox payouts on"
          }
          // A border and a dot, because the off state used to be a grey
          // pill that read as a status label - the operator could not
          // tell there was anything to click, and asked where the
          // enable button was.
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold cursor-pointer transition-colors disabled:cursor-wait ${
            row.sandbox_enabled
              ? "border-primary/40 bg-primary-container/10 text-primary hover:bg-primary-container/25"
              : "border-outline-variant bg-surface text-on-surface-variant hover:bg-surface-container-low hover:border-primary/40"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${row.sandbox_enabled ? "bg-current" : "bg-outline"}`}
          />
          {row.sandbox_enabled ? "On" : "Off"}
        </button>
      </td>

      <td className={tdClass}>
        {confirmingLive ? (
          // Named in the question. "Are you sure?" is answered yes by
          // reflex; the merchant's name is what makes a wrong row
          // visible before it is clicked.
          <div className="space-y-1.5 max-w-[15rem]">
            <p className="text-[11px] text-red-800">
              Let <span className="font-semibold">{name}</span> send <strong>real money</strong> by API
              key, with nobody approving each request?
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={pending}
                onClick={() =>
                  run(() => setPayoutLiveAction(row.merchant_id, true, row.version), () => setConfirmingLive(false))
                }
                className="rounded-lg bg-red-700 px-2.5 py-1 text-xs font-semibold text-white hover:bg-red-800 disabled:cursor-wait"
              >
                Grant live
              </button>
              <button
                type="button"
                onClick={() => setConfirmingLive(false)}
                className="text-xs font-semibold text-on-surface-variant hover:underline"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            role="switch"
            aria-checked={row.live_enabled}
            aria-label={`Live payouts for ${name}`}
            disabled={pending}
            onClick={() =>
              row.live_enabled
                ? run(() => setPayoutLiveAction(row.merchant_id, false, row.version))
                : setConfirmingLive(true)
            }
            title={
              row.live_enabled
                ? "Click to withdraw live payout access"
                : "Click to grant live payout access — real money"
            }
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold cursor-pointer transition-colors disabled:cursor-wait ${
              row.live_enabled
                ? "border-red-300 bg-red-100 text-red-800 hover:bg-red-200"
                : "border-outline-variant bg-surface text-on-surface-variant hover:bg-surface-container-low hover:border-red-300"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${row.live_enabled ? "bg-current" : "bg-outline"}`}
            />
            {row.live_enabled ? "LIVE" : "Off"}
          </button>
        )}
      </td>

      <td className={`${tdClass} text-on-surface-variant`}>
        <div className="font-mono text-xs">TZS {money(row.wallet_available)}</div>
        {Number(row.wallet_reserved) > 0 && (
          <div className="text-[11px] text-outline">TZS {money(row.wallet_reserved)} in flight</div>
        )}
        <div className="text-[11px] text-outline">{row.wallet_environment}</div>
      </td>

      <td className={`${tdClass} text-on-surface-variant text-xs`}>
        <div>per payout: {row.per_payout_limit_tzs ? `TZS ${money(row.per_payout_limit_tzs)}` : "none"}</div>
        <div>
          24h: {row.daily_limit_tzs ? `TZS ${money(row.daily_limit_tzs)}` : "none"}
          {!row.daily_limit_tzs && (
            // Not decoration. authorize_payout skips the rolling check
            // entirely when this is null, so the wallet balance is the
            // only ceiling left.
            <span className="ml-1 text-amber-700">· unlimited</span>
          )}
        </div>
      </td>

      <td className={tdClass}>
        {editingFee ? (
          <div className="flex items-start gap-1.5">
            <input
              value={feePercent}
              onChange={(event) => setFeePercent(event.target.value)}
              aria-label={`Payout fee percentage for ${name}`}
              placeholder="blank = tariff"
              className="w-24 rounded border border-outline-variant bg-transparent px-2 py-1 text-xs text-on-surface"
            />
            <button
              type="button"
              disabled={pending}
              onClick={() =>
                run(
                  () =>
                    setPayoutFeeAction(
                      row.merchant_id,
                      row.version,
                      feePercent.trim() === "" ? null : feePercent.trim(),
                      feePercent.trim() === "" ? null : (row.fee_flat_tzs ?? "0"),
                    ),
                  () => setEditingFee(false),
                )
              }
              className="rounded bg-primary-container px-2 py-1 text-xs font-semibold text-on-primary disabled:cursor-wait"
            >
              Save
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setEditingFee(true)}
            className="text-xs text-on-surface-variant hover:underline text-left"
          >
            {row.fee_percentage === null ? (
              <span className="text-outline">Standard (tariff)</span>
            ) : (
              <span className="font-medium text-on-background">{row.fee_percentage}%</span>
            )}
            {row.fee_flat_tzs && Number(row.fee_flat_tzs) > 0 && (
              <span className="text-outline"> + {money(row.fee_flat_tzs)}</span>
            )}
          </button>
        )}
      </td>

      <td className={tdClass}>
        {pausing ? (
          <div className="space-y-1.5 max-w-[14rem]">
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              aria-label={`Reason for pausing ${name}`}
              placeholder="Why? (required)"
              className="w-full rounded border border-outline-variant bg-transparent px-2 py-1 text-xs text-on-surface"
            />
            <div className="flex gap-2">
              <button
                type="button"
                disabled={pending || reason.trim() === ""}
                onClick={() =>
                  run(
                    () => setPayoutPauseAction(row.merchant_id, true, row.version, reason.trim()),
                    () => {
                      setPausing(false);
                      setReason("");
                    },
                  )
                }
                className="rounded bg-amber-700 px-2 py-1 text-xs font-semibold text-white disabled:opacity-50"
              >
                Pause
              </button>
              <button
                type="button"
                onClick={() => setPausing(false)}
                className="text-xs font-semibold text-on-surface-variant hover:underline"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : row.paused ? (
          <div className="space-y-1">
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800">
              <Icon name="pause" className="text-[12px]" />
              Paused
            </span>
            {row.paused_reason && (
              <p className="text-[11px] text-on-surface-variant max-w-[12rem]">{row.paused_reason}</p>
            )}
            <button
              type="button"
              disabled={pending}
              onClick={() => run(() => setPayoutPauseAction(row.merchant_id, false, row.version, null))}
              className="block text-[11px] font-semibold text-primary-container hover:underline"
            >
              Resume
            </button>
          </div>
        ) : (
          <button
            type="button"
            disabled={pending}
            onClick={() => setPausing(true)}
            className="text-xs font-semibold text-on-surface-variant hover:underline"
          >
            Pause
          </button>
        )}
      </td>

      <td className={`${tdClass} text-right text-xs text-on-surface-variant`}>
        {row.updated_at ? formatDateTime(row.updated_at) : "—"}
        <Link
          href={`/super-admin/merchants/${row.merchant_id}`}
          className="block text-xs font-semibold text-primary-container hover:underline mt-1"
        >
          Merchant
        </Link>
      </td>
    </tr>
  );
}
