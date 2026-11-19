import Link from "next/link";
import { Suspense } from "react";

import { AdminKpiCard } from "@/components/admin/kpi-card";
import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { CollectionsTrendChart } from "@/components/super-admin/overview/collections-trend-chart";
import { CollectionStatusDonut } from "@/components/super-admin/overview/status-donut";
import { formatCurrency, formatDateTime } from "@/lib/format";
import {
  getAdminActiveMerchantCount,
  getAdminCollectionStatusCounts,
  getAdminDailyCollectionCounts,
  getAdminOverview,
  getAdminSuccessfulCollectionsToday,
  listAdminCollectionsResult,
} from "@/lib/admin/live-api";
import { requireSuperAdmin } from "@/lib/supabase/protected-route";
import { uiPreviewEnabled } from "@/lib/auth/ui-preview";

export const metadata = {
  title: "Dashboard | InfinityPay Super Admin",
};

const MODULES = [
  { href: "/super-admin/merchants", icon: "storefront", title: "Business Management", description: "Onboard, verify & manage businesses" },
  { href: "/super-admin/invoices", icon: "receipt", title: "Invoice Management", description: "Track invoices across businesses" },
  { href: "/super-admin/withdrawals", icon: "receipt_long", title: "Withdrawal Monitoring", description: "Approve & track payouts" },
  { href: "/admin/reconciliation-center", icon: "account_balance", title: "Reconciliation Center", description: "Callback logs & unmatched txns" },
  { href: "/admin/provider-status", icon: "dns", title: "Provider Status", description: "Selcom, M-Pesa, bank uptime" },
];

/** The admin's first name, or nothing.
 *
 * Supabase stores a single `full_name`, so the first name is the first
 * whitespace-separated token. An email is deliberately NOT used as a
 * fallback greeting: "Welcome back, ceo@infinitypay.me" reads worse than
 * no name at all, which is why the plain "Welcome back" exists. */
function firstName(fullName: string | null | undefined): string | null {
  const first = (fullName ?? "").trim().split(/\s+/)[0];
  return first || null;
}

/** A lifetime total, or a dash when the backend could not produce one.
 *
 * Never TZS 0.00 for a missing value. Zero is a real and meaningful
 * answer for a daily card on a quiet morning; for an all-time total it
 * would read as "this platform has never taken a payment", which is the
 * single most alarming and least likely thing this dashboard could say.
 * A dash with "Couldn't load" underneath is honest and unmistakable. */
function lifetime(amount: string | null): string {
  return amount === null ? "—" : formatCurrency(amount, "TZS");
}

function Placeholder({ className }: { className: string }) {
  return <div className={`app-panel rounded-xl animate-pulse bg-surface-container-high ${className}`} />;
}

/* ---------------------------------------------------------------------
   Each section fetches its own data behind its own Suspense boundary,
   so the slowest does not decide when the page appears. The charts cost
   one small request per day plus one per status; the header and the
   cards do not wait for them.
   --------------------------------------------------------------------- */

async function HeaderSection() {
  // Mirrors the layout's own guard. `requireSuperAdmin()` redirects when
  // there is no platform account, which is correct in production and
  // wrong in the authentication-free preview the design workflow uses —
  // calling it unconditionally here would bounce the very page it is
  // meant to render. The layout has already authorised this request; the
  // call here is for the admin's name, with the authorization check as a
  // deliberate second layer rather than the only one.
  const user = uiPreviewEnabled() ? null : await requireSuperAdmin();
  const meta = (user?.user_metadata ?? {}) as Record<string, unknown>;
  const name = firstName(typeof meta.full_name === "string" ? meta.full_name : null);

  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="on-gradient text-3xl md:text-4xl font-semibold tracking-tight">
          {name ? `Welcome back, ${name}` : "Welcome back"}
        </h1>
        <p className="on-gradient-muted mt-1 text-sm">
          Platform operations and health · all figures in Africa/Dar_es_Salaam time.
        </p>
      </div>
      <Link
        href="/super-admin/collections"
        className="rounded-lg bg-primary-container px-4 py-2.5 text-sm font-semibold text-on-primary hover:opacity-90 transition-opacity"
      >
        View all transactions
      </Link>
    </div>
  );
}

export async function MetricsSection() {
  const [overview, activeMerchants, successfulToday] = await Promise.all([
    getAdminOverview(),
    getAdminActiveMerchantCount(),
    getAdminSuccessfulCollectionsToday(),
  ]);

  if (!overview) {
    return (
      <Card>
        <p className="text-sm text-on-surface-variant">
          Couldn&apos;t reach InfinityPay to load platform metrics. Check that apps/api is running and reachable.
        </p>
      </Card>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      <AdminKpiCard
        variant="brand"
        icon="account_balance_wallet"
        label="Collection Volume"
        value={formatCurrency(overview.collections_today, "TZS")}
        caption="Today"
      />
      <AdminKpiCard
        variant="brand"
        icon="task_alt"
        label="Successful Transactions"
        value={successfulToday === null ? "Data unavailable" : successfulToday.toLocaleString()}
        caption="Today"
      />
      <AdminKpiCard
        variant="brand"
        icon="store"
        label="Active Businesses"
        value={activeMerchants === null ? "Data unavailable" : activeMerchants.toLocaleString()}
        caption="As of now"
      />
      <AdminKpiCard
        tone="warning"
        icon="hourglass_empty"
        label="Pending Withdrawals"
        value={overview.pending_withdrawals.toLocaleString()}
        caption="Awaiting approval"
      />
      </div>

      {/* The lifetime and month-to-date figures, kept below the four
          headline cards rather than removed with them.

          `lifetime()` is why this row exists as its own thing: a
          lifetime total that failed to load must render as a dash, never
          as TZS 0.00, because "this platform has never taken a payment"
          is the most alarming and least likely sentence this dashboard
          could say. A daily card showing zero is just a quiet morning;
          the two are not interchangeable, and the distinction is
          covered by dashboard-lifetime-cards.test.tsx. */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <AdminKpiCard
          variant="brand"
          icon="account_balance"
          label="Collections Total"
          value={lifetime(overview.collections_total)}
          caption={overview.collections_total === null ? "Couldn't load" : "All time"}
        />
        <AdminKpiCard
          variant="brand"
          icon="savings"
          label="Revenue Total"
          value={lifetime(overview.revenue_total)}
          caption={overview.revenue_total === null ? "Couldn't load" : "All time"}
        />
        <AdminKpiCard
          variant="brand"
          icon="payments"
          label="Collections This Month"
          value={formatCurrency(overview.collections_this_month, "TZS")}
          caption="Month to date"
        />
        <AdminKpiCard
          variant="brand"
          icon="monetization_on"
          label="Revenue This Month"
          value={formatCurrency(overview.platform_revenue, "TZS")}
          caption="Month to date"
        />
        <AdminKpiCard
          variant="brand"
          icon="monetization_on"
          label="Revenue Today"
          value={formatCurrency(overview.platform_revenue_today, "TZS")}
          caption="Since midnight"
        />
        <AdminKpiCard
          variant="brand"
          icon="send_money"
          label="Withdrawals Today"
          value={formatCurrency(overview.withdrawals_today, "TZS")}
          caption="Today"
        />
        <AdminKpiCard
          variant="brand"
          icon="assignment_ind"
          label="Pending Onboarding"
          value={overview.pending_onboarding_requests.toLocaleString()}
          caption="Awaiting review"
        />
        <AdminKpiCard
          variant="brand"
          icon="store"
          label="Total Businesses"
          value={overview.total_merchants.toLocaleString()}
          caption="All accounts"
        />
      </div>
    </>
  );
}

async function ChartsSection() {
  const [daily, statuses] = await Promise.all([
    getAdminDailyCollectionCounts(14),
    getAdminCollectionStatusCounts(),
  ]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card className="lg:col-span-2">
        <CollectionsTrendChart points={daily} />
      </Card>
      <Card>
        <CollectionStatusDonut counts={statuses} />
      </Card>
    </div>
  );
}

async function RecentTransactionsSection() {
  const { rows, failure } = await listAdminCollectionsResult();
  const recent = rows.slice(0, 8);

  return (
    <Card padded={false}>
      <div className="flex items-center justify-between p-5 pb-3">
        <h2 className="text-lg font-semibold text-on-surface">Recent Transactions</h2>
        <Link href="/super-admin/collections" className="text-primary text-sm font-semibold hover:underline">
          View all
        </Link>
      </div>

      {failure ? (
        <p className="p-6 text-sm text-on-surface-variant" role="alert">
          Transactions couldn&apos;t be loaded ({failure}). This is not the same as there being none — open
          the Collections page to retry.
        </p>
      ) : recent.length === 0 ? (
        <p className="p-6 text-sm text-on-surface-variant">No collections recorded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[760px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-outline-variant">
                <th className={thClass}>Business</th>
                <th className={thClass}>Amount</th>
                <th className={thClass}>Method</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>When</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {recent.map((row) => (
                <tr key={row.collection_id} className="border-t border-outline-variant">
                  <td className={`${tdClass} font-medium text-on-surface`}>
                    <span className="block truncate max-w-[220px]">{row.merchant_name}</span>
                    {row.merchant_code && (
                      <span className="block text-xs font-normal text-on-surface-variant">{row.merchant_code}</span>
                    )}
                  </td>
                  <td className={`${tdClass} tabular-nums text-on-surface`}>
                    {formatCurrency(row.amount, row.currency)}
                  </td>
                  <td className={`${tdClass} text-on-surface-variant`}>{row.method}</td>
                  <td className={tdClass}>
                    <StatusPill status={row.status} />
                  </td>
                  <td className={`${tdClass} text-on-surface-variant whitespace-nowrap`}>
                    {formatDateTime(row.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** Status as a word first and a colour second — the colour is an aid to
 * finding it, never the thing that carries the meaning. */
function StatusPill({ status }: { status: string }) {
  const tone =
    status === "successful"
      ? "bg-[#15803d]/12 text-[#14532d]"
      : status === "failed"
        ? "bg-[#9f1239]/12 text-[#881337]"
        : status === "processing"
          ? "bg-[#1d4ed8]/12 text-[#1e3a8a]"
          : "bg-[#a16207]/14 text-[#713f12]";
  return (
    <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${tone}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export default function SuperAdminCommandCenterPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<Placeholder className="h-20" />}>
        <HeaderSection />
      </Suspense>

      <Suspense fallback={<Placeholder className="h-28" />}>
        <MetricsSection />
      </Suspense>

      <Suspense fallback={<Placeholder className="h-80" />}>
        <ChartsSection />
      </Suspense>

      <Suspense fallback={<Placeholder className="h-96" />}>
        <RecentTransactionsSection />
      </Suspense>

      <div>
        <h2 className="on-gradient text-lg font-semibold mb-3">Operational Modules</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {MODULES.map((module) => (
            <Link
              key={module.href}
              href={module.href}
              className="app-panel flex items-center gap-4 rounded-xl border border-surface-container-highest/60 p-4 shadow-ambient transition-colors hover:border-primary/40"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-container/15 text-primary">
                <Icon name={module.icon} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-on-surface">{module.title}</span>
                <span className="block text-xs text-on-surface-variant mt-0.5">{module.description}</span>
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
