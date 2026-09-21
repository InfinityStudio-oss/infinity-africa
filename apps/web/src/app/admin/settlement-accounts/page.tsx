import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { listSettlementAccounts } from "@/lib/admin/api";
import { settlementStatusBadge } from "@/lib/admin/status-tones";

export const metadata = {
  title: "Settlement Accounts | InfinityPay Super Admin",
};

export default async function SettlementAccountsPage() {
  const accounts = await listSettlementAccounts();
  const total = accounts.reduce((sum, account) => sum + Number(account.balance), 0);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Settlement Accounts"
        description="The platform's own settlement accounts with each payment provider and bank."
        action={
          <button className="flex items-center gap-2 bg-primary-container text-on-primary px-4 py-2.5 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity w-fit">
            <Icon name="add" className="text-[20px]" />
            Add Settlement Account
          </button>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <AdminKpiCard icon="account_balance_wallet" label="Total Settlement Balance" value={formatCurrency(String(total), "TZS")} />
        <AdminKpiCard icon="hub" label="Linked Providers" value={accounts.length.toLocaleString()} />
        <AdminKpiCard icon="hourglass_empty" label="Pending Settlements" value={formatCurrency("6200000", "TZS")} />
      </div>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Provider Settlement Accounts</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[760px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Provider</th>
                <th className={thClass}>Account Reference</th>
                <th className={thClass}>Current Balance</th>
                <th className={thClass}>Last Settled</th>
                <th className={thClass}>Status</th>
                <th className={`${thClass} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {accounts.map((account) => (
                <tr key={account.id} className="border-t border-surface-container-highest">
                  <td className={`${tdClass} font-medium text-on-background`}>{account.provider}</td>
                  <td className={`${tdClass} font-mono text-xs`}>{account.account_reference}</td>
                  <td className={`${tdClass} font-semibold text-on-background`}>{formatCurrency(account.balance, "TZS")}</td>
                  <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(account.last_settled_at)}</td>
                  <td className={tdClass}>
                    <StatusBadge {...settlementStatusBadge(account.status)} />
                  </td>
                  <td className={`${tdClass} text-right`}>
                    <button className="p-1.5 text-on-surface-variant hover:text-primary" title="View">
                      <Icon name="visibility" className="text-[18px]" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
