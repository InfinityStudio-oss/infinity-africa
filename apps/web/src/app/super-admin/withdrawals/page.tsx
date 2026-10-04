import { PageHeader } from "@/components/portal/page-header";
import { FloatBalanceCard } from "@/components/super-admin/float-balance-card";
import { WithdrawalsTable } from "@/components/super-admin/withdrawals-table";
import { getDisbursementFloatBalance, listAdminWithdrawals } from "@/lib/admin/live-api";

export const metadata = {
  title: "Withdrawals | InfinityPay Super Admin",
};

export default async function SuperAdminWithdrawalsPage() {
  const [withdrawals, queue, floatBalance] = await Promise.all([
    listAdminWithdrawals(),
    listAdminWithdrawals({ status: "PENDING_ADMIN_APPROVAL", requiresApproval: true }),
    // Never rejects — it resolves to `available: null` rather than
    // failing, so a Selcom outage cannot stop this page rendering the
    // approval queue.
    getDisbursementFloatBalance(),
  ]);

  const pendingTotal = queue
    .reduce((total, row) => total + Number(row.total_reserved_amount ?? row.amount), 0)
    .toFixed(2);

  return (
    <div className="space-y-8">
      <PageHeader title="Withdrawal Monitoring" description="Track and approve every payout leaving the platform." />
      <FloatBalanceCard balance={floatBalance} pendingTotal={pendingTotal} />
      <WithdrawalsTable rows={withdrawals} queue={queue} />
    </div>
  );
}
