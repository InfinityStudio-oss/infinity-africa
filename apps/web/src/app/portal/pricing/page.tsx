import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";

export const metadata = {
  title: "Pricing | InfinityPay Merchant Portal",
};

const FEE_SCHEDULE: Array<{ type: string; fee: string; notes: string; free?: boolean }> = [
  { type: "Mobile Money Collections", fee: "1.5% per transaction", notes: "Deducted automatically at settlement" },
  { type: "Payment Links", fee: "1.5% per transaction", notes: "Same rate as mobile money collections" },
  { type: "Invoices (Pay Now)", fee: "1.5% per transaction", notes: "Waived for invoices under TZS 10,000" },
  { type: "Withdraw to Selcom Pesa", fee: "Free", notes: "Zero fees within the Selcom network, our recommended withdrawal method", free: true },
  { type: "Withdraw to Mobile Money", fee: "1% per withdrawal", notes: "M-Pesa, Tigo Pesa, Airtel Money, HaloPesa" },
  { type: "Withdraw to Bank Account", fee: "TZS 1,500 flat fee", notes: "Same-business-day settlement" },
];

export default function PricingPage() {
  return (
    <div className="space-y-8">
      <PageHeader title="Pricing" description="Transparent, pay-as-you-go fees. No hidden charges." />

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Fee Schedule</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[640px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Transaction Type</th>
                <th className={thClass}>Fee</th>
                <th className={thClass}>Notes</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {FEE_SCHEDULE.map((row) => (
                <tr key={row.type} className="border-t border-surface-container-highest">
                  <td className={`${tdClass} font-medium text-on-background`}>{row.type}</td>
                  <td className={tdClass}>
                    {row.free ? (
                      <span className="inline-flex items-center gap-1 bg-accent text-primary px-2.5 py-1 rounded-full text-xs font-semibold border border-primary/20 w-fit">
                        <Icon name="check" className="text-[12px] font-bold" />
                        Free
                      </span>
                    ) : (
                      row.fee
                    )}
                  </td>
                  <td className={`${tdClass} text-on-surface-variant text-sm`}>{row.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <p className="text-sm text-on-surface-variant">Need a custom rate for high volume? Contact our sales team.</p>
        <button className="shrink-0 border border-outline-variant text-on-surface text-sm font-medium py-2.5 px-5 rounded-lg hover:bg-surface-container-low transition-colors">
          Contact Sales
        </button>
      </Card>
    </div>
  );
}
