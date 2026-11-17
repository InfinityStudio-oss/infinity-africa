import { Suspense, cache } from "react";

import { PageHeader } from "@/components/portal/page-header";
import { FloatBalanceCard } from "@/components/super-admin/float-balance-card";
import { WithdrawalAutomationCard } from "@/components/super-admin/withdrawal-automation-card";
import { WithdrawalsTable } from "@/components/super-admin/withdrawals-table";
import {
  getDisbursementFloatBalance,
  getWithdrawalAutomationPolicy,
  listAdminWithdrawals,
} from "@/lib/admin/live-api";

export const metadata = {
  title: "Withdrawals | InfinityPay Super Admin",
};

/**
 * Three independent sections, each behind its own Suspense boundary.
 *
 * This page used to await all four reads together before rendering
 * anything, which meant the slowest decided when the page appeared. The
 * slowest is the float balance: it is a live call out to Selcom, and the
 * endpoint behind it is explicitly built to degrade - a provider outage
 * returns `available: null` rather than failing. A figure the page is
 * designed to render without must not be the thing that decides whether
 * the page renders at all.
 *
 * So the heading paints immediately, the automation policy arrives on
 * its own single request, the table arrives when its rows do, and the
 * float balance takes as long as Selcom takes without holding up either.
 */

/** The approval queue, read once per request and shared by the two
 * sections that need it - the float card totals it, the table lists it.
 * Without this, splitting the page in two would have doubled the call. */
const loadApprovalQueue = cache(() =>
  listAdminWithdrawals({ status: "PENDING_ADMIN_APPROVAL", requiresApproval: true }),
);

async function FloatSection() {
  const [floatBalance, queue] = await Promise.all([
    // Never rejects — it resolves to `available: null` rather than
    // failing, so a Selcom outage cannot stop this page rendering.
    getDisbursementFloatBalance(),
    loadApprovalQueue(),
  ]);

  const pendingTotal = queue
    .reduce((total, row) => total + Number(row.total_reserved_amount ?? row.amount), 0)
    .toFixed(2);

  return <FloatBalanceCard balance={floatBalance} pendingTotal={pendingTotal} />;
}

async function AutomationSection() {
  // Also never rejects: null renders an explicit "couldn't load" state.
  // A blank form would read as OFF, and believing automation is off when
  // it is not is the one wrong conclusion this page must not invite.
  const policy = await getWithdrawalAutomationPolicy();
  return <WithdrawalAutomationCard policy={policy} />;
}

async function TableSection() {
  const [withdrawals, queue] = await Promise.all([listAdminWithdrawals(), loadApprovalQueue()]);
  return <WithdrawalsTable rows={withdrawals} queue={queue} />;
}

function Placeholder({ className }: { className: string }) {
  return <div className={`bg-surface-container-highest rounded-xl animate-pulse ${className}`} />;
}

export default function SuperAdminWithdrawalsPage() {
  return (
    <div className="space-y-8">
      <PageHeader title="Withdrawal Monitoring" description="Track and approve every payout leaving the platform." />

      <Suspense fallback={<Placeholder className="h-20" />}>
        <FloatSection />
      </Suspense>

      {/* Above the list, because it decides how much of that list there
          will be. The two are deliberately separate: an amount being
          within the automatic limits is not an approval, and the queue
          below is the only thing that says what is actually waiting. */}
      <Suspense fallback={<Placeholder className="h-64" />}>
        <AutomationSection />
      </Suspense>

      <Suspense fallback={<Placeholder className="h-96" />}>
        <TableSection />
      </Suspense>
    </div>
  );
}
