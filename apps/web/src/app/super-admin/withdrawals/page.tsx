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

export default async function SuperAdminWithdrawalsPage() {
  const [withdrawals, queue, floatBalance, automationPolicy] = await Promise.all([
    listAdminWithdrawals(),
    listAdminWithdrawals({ status: "PENDING_ADMIN_APPROVAL", requiresApproval: true }),
    // Never rejects — it resolves to `available: null` rather than
    // failing, so a Selcom outage cannot stop this page rendering the
    // approval queue.
    getDisbursementFloatBalance(),
    // Also never rejects: null renders an explicit "couldn't load" state.
    // A blank form would read as OFF, and believing automation is off
    // when it is not is the one wrong conclusion this page must not
    // invite.
    getWithdrawalAutomationPolicy(),
  ]);

  const pendingTotal = queue
    .reduce((total, row) => total + Number(row.total_reserved_amount ?? row.amount), 0)
    .toFixed(2);

  return (
    <div className="space-y-8">
      <PageHeader title="Withdrawal Monitoring" description="Track and approve every payout leaving the platform." />
      <FloatBalanceCard balance={floatBalance} pendingTotal={pendingTotal} />
      {/* Above the list, because it decides how much of that list there
          will be. The two are deliberately separate: an amount being
          within the automatic limits is not an approval, and the queue
          below is the only thing that says what is actually waiting. */}
      <WithdrawalAutomationCard policy={automationPolicy} />
      <WithdrawalsTable rows={withdrawals} queue={queue} />
    </div>
  );
}
