import { PageHeader } from "@/components/portal/page-header";
import { WithdrawalsTable } from "@/components/super-admin/withdrawals-table";
import { listAdminWithdrawals } from "@/lib/admin/live-api";

export const metadata = {
  title: "Withdrawals | InfinityPay Super Admin",
};

export default async function SuperAdminWithdrawalsPage() {
  const [withdrawals, queue] = await Promise.all([
    listAdminWithdrawals(),
    listAdminWithdrawals({ status: "PENDING_ADMIN_APPROVAL", requiresApproval: true }),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader title="Withdrawal Monitoring" description="Track and approve every payout leaving the platform." />
      <WithdrawalsTable rows={withdrawals} queue={queue} />
    </div>
  );
}
