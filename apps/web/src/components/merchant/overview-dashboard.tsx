"use client";

import { useCallback, useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { KpiCard } from "@/components/portal/kpi-card";
import { formatCurrency } from "@/lib/format";
import { getOverviewReport } from "@/lib/portal/api";
import type { MerchantOverview } from "@/lib/portal/api";
import type { MerchantOverviewReport, PayoutWallet } from "@/lib/portal/types";

import { CollectionsBarChart } from "./overview/collections-bar-chart";
import { CollectionsDonut } from "./overview/collections-donut";
import { OverviewHeader } from "./overview/overview-header";
import type { DateRangeKey } from "./overview/overview-header";
import { SetupChecklist } from "./overview/setup-checklist";
import type { ChecklistTask } from "./overview/setup-checklist";

/**
 * The merchant Overview: greeting, reporting, then setup.
 *
 * Order matters here and is the point of the layout. Charts first,
 * because a working account opens this page to see how trading is going;
 * cards underneath, because they are the same story at lower resolution;
 * setup last, because it is what a new account needs and a verified one
 * has finished with.
 *
 * Two kinds of number live on this page and they must not be confused:
 *
 *   - **Reporting** (the charts, Successful Collections, Fees Paid) is
 *     scoped to the chosen period.
 *   - **Balances** (Available Balance, the Payout Wallet) are current
 *     ledger positions and ignore the date filter entirely. A balance
 *     that moved when someone picked "Last 7 days" would be telling them
 *     their money had changed, which it has not.
 */

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Today in Africa/Dar_es_Salaam, as YYYY-MM-DD. Deliberately not
 * toISOString(), which is UTC and lands on the wrong day for three hours
 * every evening. */
function dayInDarEsSalaam(date: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Dar_es_Salaam",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "01";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return dayInDarEsSalaam(date);
}

function buildTasks(overview: MerchantOverview): ChecklistTask[] {
  const kyc = overview.merchant.kyc_status;
  return [
    {
      id: "verify",
      label: "Verify your business",
      description: "Upload your registration and ID so you can accept live payments.",
      href: "/onboarding",
      done: kyc === "VERIFIED" || kyc === "APPROVED",
      icon: "verified_user",
    },
    {
      id: "payment-link",
      label: "Create your first payment link",
      description: "The fastest way to take a payment without writing code.",
      href: "/dashboard/pay-by-link",
      done: overview.active_payment_links > 0,
      icon: "add_link",
    },
    {
      id: "collect",
      label: "Take your first payment",
      description: "Share a link or connect your system, then watch it land here.",
      href: "/portal/collections",
      done: Number(overview.total_collections) > 0,
      icon: "payments",
    },
    {
      id: "api",
      label: "Connect your system",
      description: "Issue an API key to collect and reconcile automatically.",
      href: "/portal/api-credentials",
      done: false,
      icon: "vpn_key",
    },
  ];
}

export function OverviewDashboard({
  overview,
  initialReport,
  payoutWallet,
  canCreatePaymentLink = true,
}: {
  overview: MerchantOverview;
  /** Fetched on the server for the default period, so the first paint
   * already has the charts rather than a spinner. */
  initialReport: MerchantOverviewReport | null;
  /** Null when this merchant has no Disbursement API access - the card
   * is then not rendered at all rather than shown empty. */
  payoutWallet: PayoutWallet | null;
  canCreatePaymentLink?: boolean;
}) {
  const currency = overview.merchant.currency;

  const [range, setRange] = useState<DateRangeKey>("7d");
  const [customStart, setCustomStart] = useState(daysAgo(6));
  const [customEnd, setCustomEnd] = useState(dayInDarEsSalaam());
  const [report, setReport] = useState<MerchantOverviewReport | null>(initialReport);
  const [loading, setLoading] = useState(false);
  // Null means "no error". An empty report and a failed fetch are
  // different screens: showing zeros for a failed load tells a merchant
  // they took nothing, which may be false.
  const [error, setError] = useState<string | null>(initialReport ? null : "load-failed");

  const load = useCallback(
    async (next: DateRangeKey, start: string, end: string) => {
      setLoading(true);
      setError(null);
      const params =
        next === "custom" ? { startDate: start, endDate: end } : { days: next === "30d" ? 30 : 7 };
      const result = await getOverviewReport(params);
      if (result.error || !result.data) {
        setError(result.error ?? "load-failed");
        setReport(null);
      } else {
        setReport(result.data);
      }
      setLoading(false);
    },
    [],
  );

  // Skips the first render: the server already fetched the default
  // period, and refetching it immediately would make the page flash.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    if (!hydrated) {
      setHydrated(true);
      return;
    }
    void load(range, customStart, customEnd);
  }, [range, customStart, customEnd, hydrated, load]);

  const tasks = buildTasks(overview);

  return (
    <div className="space-y-6">
      <OverviewHeader
        businessName={overview.merchant.business_name}
        accountStatus={overview.merchant.kyc_status}
        range={range}
        onRangeChange={setRange}
        customStart={customStart}
        customEnd={customEnd}
        onCustomChange={(start, end) => {
          setCustomStart(start);
          setCustomEnd(end);
        }}
        canCreatePaymentLink={canCreatePaymentLink}
      />

      {/* Charts first. Two thirds / one third on desktop; stacked on a
          phone, where side-by-side would make both unreadable. */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          {loading ? (
            <ChartSkeleton title="Collections over time" />
          ) : error ? (
            <ChartError onRetry={() => void load(range, customStart, customEnd)} />
          ) : (
            <CollectionsBarChart series={report?.series ?? []} currency={currency} />
          )}
        </Card>
        <Card>
          {loading ? (
            <ChartSkeleton title="Collections by payment method" />
          ) : error ? (
            <ChartError onRetry={() => void load(range, customStart, customEnd)} />
          ) : (
            <CollectionsDonut
              byMethod={report?.by_method ?? []}
              currency={currency}
              startDate={report?.start_date}
              endDate={report?.end_date}
            />
          )}
        </Card>
      </div>

      {/* Two per row on a phone where the numbers are short enough to fit. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          icon="account_balance_wallet"
          label="Available Balance"
          value={formatCurrency(overview.available_balance, currency)}
          caption="Current balance"
        />
        <KpiCard
          icon="payments"
          label="Successful Collections"
          value={error ? "—" : formatCurrency(report?.successful_collections ?? "0", currency)}
          caption={error ? "Could not load" : `${report?.successful_count ?? 0} payments`}
        />
        <KpiCard
          icon="request_quote"
          label="Fees Paid"
          value={error ? "—" : formatCurrency(report?.fees_paid ?? "0", currency)}
          caption={error ? "Could not load" : "In this period"}
        />
        <KpiCard
          icon="hourglass_top"
          label="Pending Collections"
          value={error ? "—" : formatCurrency(report?.pending_collections ?? "0", currency)}
          caption={error ? "Could not load" : `${report?.pending_count ?? 0} in flight`}
        />
      </div>

      {payoutWallet && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <Icon name="send_money" className="text-accent-text" />
              <div>
                <h2 className="text-base font-semibold text-on-surface">Payout Wallet</h2>
                <p className="text-sm text-on-surface-variant">
                  Prefunded balance your API keys can send from
                  {payoutWallet.environment === "sandbox" ? " (sandbox)" : ""}.
                </p>
              </div>
            </div>
            <div className="flex gap-8">
              <div>
                <p className="text-xs text-on-surface-variant">Available</p>
                <p className="text-lg font-bold text-on-surface tabular-nums">
                  {formatCurrency(payoutWallet.available, payoutWallet.currency)}
                </p>
              </div>
              <div>
                <p className="text-xs text-on-surface-variant">Reserved</p>
                <p className="text-lg font-bold text-on-surface tabular-nums">
                  {formatCurrency(payoutWallet.reserved, payoutWallet.currency)}
                </p>
              </div>
            </div>
          </div>
        </Card>
      )}

      <SetupChecklist tasks={tasks} />
    </div>
  );
}

function ChartSkeleton({ title }: { title: string }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-on-surface">{title}</h2>
      <p className="mt-0.5 text-sm text-on-surface-variant">Loading…</p>
      <div
        className="mt-5 h-48 rounded-lg bg-surface-container-high animate-pulse"
        aria-hidden
      />
    </div>
  );
}

function ChartError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="py-8 text-center">
      <Icon name="error" className="text-[32px] text-on-surface-variant" />
      {/* Never a zero. A merchant told they collected nothing, when in
          fact the request failed, will go looking for missing money. */}
      <p className="mt-2 text-sm font-medium text-on-surface">
        Couldn&apos;t load this period&apos;s figures
      </p>
      <p className="mt-1 text-sm text-on-surface-variant">
        Your money is unaffected — this is a reporting problem.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-semibold"
      >
        Try again
      </button>
    </div>
  );
}
