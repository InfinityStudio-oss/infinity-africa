"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { KpiCard } from "@/components/portal/kpi-card";
import { PageHeader } from "@/components/portal/page-header";
import { formatCurrency } from "@/lib/format";
import { createMerchantReferralCode, getMerchantReferrals } from "@/lib/portal/api";
import type { MerchantReferralSummary } from "@/lib/portal/types";

/** What a merchant is told, in the words that match the rule the backend
 * enforces. Stated plainly and up front rather than in small print,
 * because the one thing a referrer needs to understand is that inviting
 * people is not what earns the money. */
const HOW_IT_WORKS = [
  "Share your link with a business you think should be on InfinityPay.",
  "They sign up and InfinityPay reviews and approves them.",
  "You earn a share of what InfinityPay makes from their payments in their first 30 days.",
  "InfinityPay reviews each commission before it is paid.",
];

export default function MerchantReferralsPage() {
  const [summary, setSummary] = useState<MerchantReferralSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getMerchantReferrals()
      .then(setSummary)
      .finally(() => setLoading(false));
  }, []);

  async function handleCreateCode() {
    setCreating(true);
    setError(null);
    try {
      setSummary(await createMerchantReferralCode());
    } catch (err) {
      // The backend's own message: "Your account needs to be approved
      // before you can invite other businesses" is something the merchant
      // can act on, and a generic line would hide it.
      setError(err instanceof Error ? err.message : "Couldn't create your referral code. Try again.");
    } finally {
      setCreating(false);
    }
  }

  async function handleCopy() {
    if (!summary?.referral_link) return;
    try {
      await navigator.clipboard.writeText(summary.referral_link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard needs HTTPS and permission. The link stays on screen and
      // selectable, so this button is a convenience, never the only way.
    }
  }

  const currency = summary?.currency ?? "TZS";

  return (
    <div className="space-y-8">
      <PageHeader
        title="Invite a business"
        description="Earn a share of what InfinityPay makes from businesses you bring to the platform."
      />

      <Card>
        <h3 className="text-xl font-semibold text-on-background">Your referral link</h3>

        {loading ? (
          <p className="mt-3 text-sm text-on-surface-variant">Loading…</p>
        ) : summary?.referral_link ? (
          <>
            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
              <code className="flex-1 min-w-0 break-all rounded-lg bg-surface-container-low px-4 py-3 font-mono text-sm text-on-surface">
                {summary.referral_link}
              </code>
              <button
                type="button"
                onClick={handleCopy}
                className="flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-outline-variant px-4 py-3 text-sm font-medium hover:bg-surface-variant/40"
              >
                <Icon name={copied ? "check" : "content_copy"} className="text-[18px]" />
                {copied ? "Copied" : "Copy link"}
              </button>
            </div>
            <p className="mt-2 text-sm text-on-surface-variant">
              Your code is <span className="font-mono font-semibold">{summary.referral_code}</span>. A
              business can also type it in on the signup form.
            </p>
            {summary.referral_code_status !== "active" && (
              <p className="mt-3 rounded-lg bg-error-container/10 px-3.5 py-2.5 text-sm text-error">
                This referral code is currently disabled. Contact support if you think that is a mistake.
              </p>
            )}
          </>
        ) : (
          <>
            <p className="mt-3 text-sm text-on-surface-variant">
              Create your referral link to start inviting businesses.
            </p>
            {error && (
              <p role="alert" className="mt-3 rounded-lg bg-error-container/10 px-3.5 py-2.5 text-sm text-error">
                {error}
              </p>
            )}
            <button
              type="button"
              onClick={handleCreateCode}
              disabled={creating}
              className="mt-4 rounded-lg bg-primary-container px-6 py-3 text-sm font-medium text-on-primary hover:opacity-90 disabled:opacity-60"
            >
              {creating ? "Creating…" : "Create my referral link"}
            </button>
          </>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <KpiCard icon="group_add" label="Businesses invited" value={(summary?.total_invited ?? 0).toLocaleString()} />
        <KpiCard icon="verified" label="Approved" value={(summary?.approved_referrals ?? 0).toLocaleString()} />
        <KpiCard
          icon="workspace_premium"
          label="Qualified"
          value={(summary?.qualified_referrals ?? 0).toLocaleString()}
          caption="Approved and trading enough to earn"
        />
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <KpiCard
          icon="hourglass_empty"
          label="Pending commission"
          value={formatCurrency(summary?.pending_commission ?? "0", currency)}
          caption="Still building, or waiting on review"
        />
        <KpiCard
          icon="task_alt"
          label="Approved"
          value={formatCurrency(summary?.approved_commission ?? "0", currency)}
          caption="Reviewed, awaiting payout"
        />
        <KpiCard
          icon="payments"
          label="Paid"
          value={formatCurrency(summary?.paid_commission ?? "0", currency)}
        />
      </div>

      <Card>
        <h3 className="text-xl font-semibold text-on-background">How it works</h3>
        <ol className="mt-4 space-y-3">
          {HOW_IT_WORKS.map((step, index) => (
            <li key={step} className="flex gap-3 text-sm text-on-surface-variant">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-container/15 text-xs font-semibold text-primary-container">
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
        <p className="mt-5 rounded-lg bg-surface-container-low px-4 py-3 text-sm text-on-surface-variant">
          Commission is earned only when a referred business is approved and processes successful
          transactions — not for signing up. It is calculated from what InfinityPay earns on their
          payments, and reviewed by InfinityPay before payout.
        </p>
      </Card>
    </div>
  );
}
