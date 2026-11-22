import { Card } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { PayoutAccessTable } from "@/components/super-admin/payout-access-table";
import { PayoutTariffCard } from "@/components/super-admin/payout-tariff-card";
import { ProviderHealthCard } from "@/components/super-admin/provider-health-card";
import { StuckPayoutsTable } from "@/components/super-admin/stuck-payouts-table";
import {
  getAdminPayoutTariff,
  getAdminProviderHealth,
  listAdminPayoutAccess,
  listAdminPayouts,
} from "@/lib/admin/live-api";

export const metadata = {
  title: "Payouts | InfinityPay Super Admin",
};

export default async function SuperAdminPayoutsPage(props: PageProps<"/super-admin/payouts">) {
  const params = await props.searchParams;
  const page = Number(typeof params.page === "string" ? params.page : "1") || 1;

  // Two independent reads. The tariff is null when its migration has
  // not been applied, which the card says in words - a missing table
  // must not render as "0%" on the screen that sets the price.
  const [{ rows }, tariff, stuck, sandboxHealth, liveHealth] = await Promise.all([
    listAdminPayoutAccess({ page }),
    getAdminPayoutTariff(),
    // Defaults to needs_reconciliation: money held with no answer from
    // the provider, and the only status an operator must act on.
    listAdminPayouts(),
    getAdminProviderHealth("sandbox"),
    getAdminProviderHealth("live"),
  ]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payouts"
        description="Who may send money out through the Disbursement API, within what limits, at what price."
      />

      <Card>
        <p className="text-sm text-on-surface-variant">
          A payout key sends money <strong>without anyone approving each request</strong>. What caps
          it is the business&apos;s payout wallet balance, which only they can top up from their own
          dashboard behind two-factor authentication — and the limits set here. Granting{" "}
          <strong>live</strong> means real money leaves on an API call.
        </p>
      </Card>

      <ProviderHealthCard
        health={[
          { environment: "sandbox", result: sandboxHealth },
          { environment: "live", result: liveHealth },
        ]}
      />

      <PayoutTariffCard tariff={tariff} />

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-on-background">Needs a decision</h2>
          <p className="text-sm text-on-surface-variant max-w-2xl">
            Payouts parked in reconciliation. The money is held and the provider has not told us
            what happened — releasing it is a judgement that it was never paid.
          </p>
        </div>
        <StuckPayoutsTable rows={stuck.rows} />
      </section>

      <section className="space-y-3">
        <h2 className="text-base font-semibold text-on-background">Access</h2>
        <PayoutAccessTable rows={rows} />
      </section>
    </div>
  );
}
