"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { RequestPayoutAccess } from "@/components/merchant/request-payout-access";
import { Icon } from "@/components/portal/icon";
import { KpiCard } from "@/components/portal/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import type { BadgeTone } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { PayoutFundingCode } from "@/components/merchant/payout-funding-code";
import type { WithdrawalOtpChallenge } from "@/lib/portal/api";
import {
  getPayoutWallet,
  listPayouts,
  startPayoutWalletFunding,
  verifyPayoutWalletFunding,
} from "@/lib/portal/api";
import type { Payout, PayoutStatus, PayoutWallet } from "@/lib/portal/types";

/**
 * `needs_reconciliation` is the one that has to be explained rather than
 * labelled. It means the provider has not told us whether the money went
 * out, and the funds are STILL HELD because of that - nothing releases a
 * reserve on a timeout, since a payout that may have been paid must not
 * have its funds handed back for spending. A merchant seeing "failed"
 * there would reasonably assume their money is available again.
 */
const STATUS_TONE: Record<PayoutStatus, { tone: BadgeTone; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  processing: { tone: "pending", label: "Sending" },
  needs_reconciliation: { tone: "pending", label: "Confirming" },
  successful: { tone: "positive-solid", label: "Paid" },
  failed: { tone: "negative", label: "Failed" },
  cancelled: { tone: "neutral", label: "Cancelled" },
  reversed: { tone: "negative", label: "Reversed" },
};

const STATUS_HELP: Partial<Record<PayoutStatus, string>> = {
  processing: "Sent to the mobile money provider. Funds are reserved until it confirms.",
  needs_reconciliation:
    "The provider has not confirmed this payout yet, so the funds stay reserved. We keep checking — nothing is released until we know.",
  failed: "The provider declined this payout. The funds went back to your payout wallet.",
  reversed: "This payout was reversed after it settled.",
  cancelled: "This payout never left — either a limit or your balance stopped it.",
};

export default function PayoutsPage() {
  const [wallet, setWallet] = useState<PayoutWallet | null>(null);
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [loading, setLoading] = useState(true);
  const [noAccess, setNoAccess] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [fundOpen, setFundOpen] = useState(false);
  const [fundAmount, setFundAmount] = useState("");
  const [funding, setFunding] = useState(false);
  const [fundError, setFundError] = useState<string | null>(null);
  const [fundSuccess, setFundSuccess] = useState<string | null>(null);
  // Set once a code has been emailed. Its presence is what shows the
  // code box; the money has not moved while it is set.
  const [fundChallenge, setFundChallenge] = useState<WithdrawalOtpChallenge | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [walletResult, payoutsResult] = await Promise.all([getPayoutWallet(), listPayouts()]);

    // No access and a failed request are different screens. Telling a
    // merchant "no payouts yet" when the backend refused the call is how
    // a real outage gets mistaken for an empty state.
    if (walletResult.noAccess) {
      setNoAccess(true);
      setLoadError(null);
    } else if (walletResult.error) {
      setNoAccess(false);
      setLoadError(walletResult.error);
    } else {
      setNoAccess(false);
      setLoadError(null);
      setWallet(walletResult.data);
    }
    setPayouts(payoutsResult.data ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // A code can outlive the page that asked for it. If the server still
  // has one outstanding, offer the box again rather than leaving the
  // merchant with a valid code in their inbox and nowhere to type it.
  useEffect(() => {
    if (!wallet?.pending_funding_challenge_id) return;
    setFundOpen(true);
    setFundAmount((current) => current || (wallet.pending_funding_amount ?? ""));
    setFundChallenge((current) =>
      current ?? {
        otp_required: true,
        challenge_id: wallet.pending_funding_challenge_id!,
        masked_email: wallet.pending_funding_masked_email ?? "your email",
        expires_at: wallet.pending_funding_expires_at ?? "",
        resend_cooldown_seconds: 60,
        max_attempts: 5,
      },
    );
  }, [wallet]);

  async function submitFunding(event: React.FormEvent) {
    event.preventDefault();
    setFundError(null);
    setFundSuccess(null);
    setFunding(true);
    try {
      // Emails a code and moves nothing. The transfer happens in
      // confirmFunding, from the amount stored on the challenge - so a
      // code can never be applied to a different amount than the one
      // the merchant was emailed about.
      const challenge = await startPayoutWalletFunding({
        amount: fundAmount,
        currency: wallet?.currency ?? "TZS",
        environment: wallet?.environment ?? "sandbox",
      });
      setFundChallenge(challenge);
    } catch (error) {
      // The backend's own message, not a generic one: it is the
      // difference between "payouts are paused", "this account has no
      // contact email" and "your Collections balance cannot cover
      // this", and the merchant needs to know which.
      setFundError(error instanceof Error ? error.message : "Funding failed.");
    } finally {
      setFunding(false);
    }
  }

  async function confirmFunding(code: string) {
    if (!fundChallenge) return;
    const updated = await verifyPayoutWalletFunding(fundChallenge.challenge_id, code);
    setWallet(updated);
    setFundSuccess(`Moved ${formatCurrency(fundAmount, updated.currency)} into your payout wallet.`);
    setFundAmount("");
    setFundOpen(false);
    setFundChallenge(null);
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Payouts" description="Send money out through the Disbursement API" />
        <div className="text-sm on-gradient-muted">Loading…</div>
      </div>
    );
  }

  if (noAccess) {
    return (
      <div className="space-y-6">
        <PageHeader title="Payouts" description="Send money out through the Disbursement API" />
        <Card>
          <div className="p-8 text-center">
            <Icon name="send_money" className="text-[40px] text-on-surface-variant" />
            <h2 className="mt-3 text-lg font-semibold">The Disbursement API is not enabled yet</h2>
            <p className="mt-2 text-sm text-on-surface-variant max-w-xl mx-auto">
              Payouts let your own server send money out automatically, from a payout wallet you fund
              in advance. It is granted per account, one environment at a time, and starts in the
              sandbox where no real money moves.
            </p>
            <RequestPayoutAccess />
          </div>
        </Card>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Payouts" description="Send money out through the Disbursement API" />
        <Card>
          <div className="p-6">
            <p className="text-sm text-red-700 font-medium">{loadError}</p>
            <button
              onClick={() => void load()}
              className="mt-3 px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-semibold"
            >
              Try again
            </button>
          </div>
        </Card>
      </div>
    );
  }

  const currency = wallet?.currency ?? "TZS";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payouts"
        description="Send money out through the Disbursement API"
        action={
          wallet?.can_fund ? (
            <button
              onClick={() => setFundOpen((open) => !open)}
              className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-semibold inline-flex items-center gap-2"
            >
              <Icon name="add" />
              Fund payout wallet
            </button>
          ) : null
        }
      />

      {wallet?.environment === "sandbox" && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
          <span className="font-semibold">Sandbox.</span> These payouts are simulated — no real money
          moves and no real recipient is paid.
        </div>
      )}

      {wallet?.paused && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm">
          <span className="font-semibold">Payouts are paused on this account.</span>{" "}
          {wallet.paused_reason ?? "Contact InfinityPay support."} Payouts already sent are
          unaffected.
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          label="Available to pay out"
          value={formatCurrency(wallet?.available ?? "0", currency)}
          icon="account_balance_wallet"
        />
        {/* Reserved is still the merchant's money, but it is not theirs to
            spend - it is committed to payouts in flight. Showing it beside
            available is what stops "where did my balance go". */}
        <KpiCard
          label="Reserved (in flight)"
          value={formatCurrency(wallet?.reserved ?? "0", currency)}
          icon="hourglass_top"
        />
        <KpiCard
          label="Daily limit"
          value={wallet?.daily_limit_tzs ? formatCurrency(wallet.daily_limit_tzs, currency) : "—"}
          icon="speed"
        />
      </div>

      {fundOpen && wallet?.can_fund && (
        <Card>
          <form onSubmit={submitFunding} className="space-y-4">
            <div>
              <h2 className="text-base font-semibold">Fund your payout wallet</h2>
              <p className="mt-1 text-sm text-on-surface-variant">
                Moves settled money from your Collections balance into the payout wallet. Your API
                keys can only ever spend what is in here — that is the cap on what a leaked key
                could cost you.
              </p>
            </div>
            <div>
              <label htmlFor="fund-amount" className="block text-sm font-medium mb-1">
                Amount ({currency})
              </label>
              <input
                id="fund-amount"
                type="number"
                min="1"
                step="0.01"
                required
                value={fundAmount}
                onChange={(event) => setFundAmount(event.target.value)}
                className="w-full max-w-xs px-3 py-2 rounded-lg border border-surface-container-highest bg-surface text-sm"
              />
            </div>
            {fundError && <p className="text-sm text-red-700 font-medium">{fundError}</p>}
            {/* Once a code is out, the amount box and Move funds button
                are no longer the thing to act on - the code is. */}
            {fundChallenge && (
              <PayoutFundingCode
                challenge={fundChallenge}
                amountLabel={formatCurrency(fundAmount, currency)}
                onConfirm={confirmFunding}
                onCancel={() => setFundChallenge(null)}
              />
            )}
            <div className={`flex items-center gap-2 ${fundChallenge ? "hidden" : ""}`}>
              <button
                type="submit"
                disabled={funding || wallet.paused}
                className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-semibold disabled:opacity-50"
              >
                {funding ? "Moving…" : "Move funds"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setFundOpen(false);
                  setFundError(null);
                }}
                className="px-4 py-2 rounded-lg border border-surface-container-highest text-sm font-medium"
              >
                Cancel
              </button>
            </div>
            <p className="text-xs text-on-surface-variant">
              Funding requires two-factor authentication.
            </p>
          </form>
        </Card>
      )}

      {fundSuccess && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm">
          {fundSuccess}
        </div>
      )}

      <Card padded={false}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-surface-container-highest/60">
          <h2 className="text-base font-semibold">Payout history</h2>
          <button
            onClick={() => void load()}
            className="text-sm text-on-surface-variant hover:text-on-surface inline-flex items-center gap-1"
          >
            <Icon name="refresh" className="text-[18px]" />
            Refresh
          </button>
        </div>
        {payouts.length === 0 ? (
          <div className="p-8 text-center text-sm text-on-surface-variant">
            No payouts yet. Your server creates these by calling{" "}
            <code className="px-1 py-0.5 rounded bg-surface-container-highest text-xs">POST /v1/payouts</code>{" "}
            with a payout API key.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className={thClass}>Reference</th>
                  <th className={thClass}>Amount</th>
                  <th className={thClass}>Fee</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Created</th>
                </tr>
              </thead>
              <tbody>
                {payouts.map((payout) => {
                  const tone = STATUS_TONE[payout.status] ?? { tone: "neutral" as BadgeTone, label: payout.status };
                  const help = STATUS_HELP[payout.status];
                  return (
                    <tr key={payout.id} className="border-t border-surface-container-highest/60">
                      <td className={tdClass}>
                        <span className="font-mono text-xs">{payout.reference}</span>
                      </td>
                      <td className={tdClass}>{formatCurrency(payout.amount, payout.currency)}</td>
                      <td className={tdClass}>{formatCurrency(payout.fee_amount, payout.currency)}</td>
                      <td className={tdClass}>
                        <StatusBadge tone={tone.tone} label={tone.label} />
                        {help && <p className="mt-1 text-xs text-on-surface-variant max-w-xs">{help}</p>}
                        {payout.failure_reason && (
                          <p className="mt-1 text-xs text-on-surface-variant max-w-xs">{payout.failure_reason}</p>
                        )}
                      </td>
                      <td className={tdClass}>{formatDateTime(payout.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
