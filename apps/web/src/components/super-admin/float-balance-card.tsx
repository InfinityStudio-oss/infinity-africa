import { Icon } from "@/components/portal/icon";
import { formatCurrency } from "@/lib/format";
import type { DisbursementFloatBalance } from "@/lib/admin/types";

/**
 * The platform's own Selcom disbursement float.
 *
 * This is the number that decides whether approving a withdrawal can
 * actually pay out. An empty float does not announce itself — Selcom
 * rejects the payout call with HTTP 400 and the withdrawal fails, which
 * the merchant sees before anyone here does. Putting the figure above
 * the approval queue turns that into something checkable beforehand.
 *
 * Note this is not any merchant's money. It is the platform's own
 * account that payouts are funded from, which is why it sits here rather
 * than anywhere a merchant can see.
 */
export function FloatBalanceCard({
  balance,
  pendingTotal,
  currency = "TZS",
}: {
  balance: DisbursementFloatBalance;
  /** Total of everything currently awaiting approval, so the two numbers
   * can be compared at a glance. */
  pendingTotal: string;
  currency?: string;
}) {
  if (balance.available === null) {
    return (
      <div className="rounded-xl border border-outline-variant bg-surface-container-lowest px-4 py-3 flex items-start gap-3">
        <Icon name="account_balance_wallet" className="text-on-surface-variant text-[20px] mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-on-background">Selcom float balance unavailable</p>
          <p className="text-xs text-on-surface-variant mt-0.5">{UNAVAILABLE_REASONS[balance.reason ?? "provider_unavailable"]}</p>
        </div>
      </div>
    );
  }

  // Deliberately a plain comparison of two decimal strings via Number:
  // both come from the same currency and are far below the precision
  // where float comparison misleads, and this only decides whether to
  // show a warning, never what is paid.
  const available = Number(balance.available);
  const pending = Number(pendingTotal);
  const short = available < pending;
  const empty = available <= 0;

  const tone = empty || short ? "border-error/40 bg-error/5" : "border-outline-variant bg-surface-container-lowest";

  return (
    <div className={`rounded-xl border px-4 py-3 flex flex-wrap items-center justify-between gap-4 ${tone}`}>
      <div className="flex items-start gap-3">
        <Icon
          name={empty || short ? "warning" : "account_balance_wallet"}
          className={`text-[20px] mt-0.5 ${empty || short ? "text-error" : "text-on-surface-variant"}`}
        />
        <div>
          <p className="text-sm font-semibold text-on-background">
            Selcom float: {formatCurrency(balance.available, balance.currency || currency)}
          </p>
          <p className="text-xs text-on-surface-variant mt-0.5">
            {empty
              ? "Payouts will fail until this account is topped up."
              : short
                ? `Less than the ${formatCurrency(pendingTotal, currency)} awaiting approval — some payouts will fail.`
                : `Covers the ${formatCurrency(pendingTotal, currency)} awaiting approval.`}
          </p>
        </div>
      </div>
    </div>
  );
}

const UNAVAILABLE_REASONS: Record<string, string> = {
  not_configured: "No Selcom disbursement account number is configured for this deployment.",
  provider_unavailable: "Selcom could not be reached. Approving still works; the balance just isn't shown.",
  unrecognised_response:
    "Selcom answered in a shape this platform doesn't recognise. Showing nothing rather than a number that might be wrong.",
};
