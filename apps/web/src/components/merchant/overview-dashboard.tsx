"use client";

import { useCallback, useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { KpiCard } from "@/components/portal/kpi-card";
import { formatCurrency } from "@/lib/format";
import { getOverviewReport, getPayoutWallet, readMerchantOverview } from "@/lib/portal/api";
import type { MerchantOverview } from "@/lib/portal/api";
import type { MerchantOverviewReport, PayoutWallet } from "@/lib/portal/types";

import { CollectionsBarChart } from "./overview/collections-bar-chart";
import { CollectionsDonut } from "./overview/collections-donut";
import { OverviewHeader } from "./overview/overview-header";
import type { DateRangeKey } from "./overview/overview-header";

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
 *   - **Reporting** (the charts, Successful Collections, Average Payment) is
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

export function OverviewDashboard({
  canCreatePaymentLink = true,
}: {
  canCreatePaymentLink?: boolean;
} = {}) {
  // Fetched here, on the client, and not by the server component that
  // renders this. lib/portal/api.ts signs requests with the browser
  // session; on the server it has none, so every call came back 401 and
  // the page silently showed the first-run screen instead.
  const [overview, setOverview] = useState<MerchantOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [payoutWallet, setPayoutWallet] = useState<PayoutWallet | null>(null);
  const [booting, setBooting] = useState(true);

  const currency = overview?.merchant.currency ?? "TZS";

  const [range, setRange] = useState<DateRangeKey>("7d");
  const [customStart, setCustomStart] = useState(daysAgo(6));
  const [customEnd, setCustomEnd] = useState(dayInDarEsSalaam());
  const [report, setReport] = useState<MerchantOverviewReport | null>(null);
  const [loading, setLoading] = useState(true);
  // Null means "no error". An empty report and a failed fetch are
  // different screens: showing zeros for a failed load tells a merchant
  // they took nothing, which may be false.
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [merchant, wallet] = await Promise.all([
        readMerchantOverview(),
        getPayoutWallet(),
      ]);
      if (cancelled) return;
      setOverview(merchant.data);
      setOverviewError(merchant.error);
      // noAccess means no Disbursement API for this merchant, so the
      // card is not rendered at all rather than shown empty.
      setPayoutWallet(wallet.data);
      setBooting(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void load(range, customStart, customEnd);
  }, [range, customStart, customEnd, load]);

  return (
    <div className="space-y-6">
      <OverviewHeader
        businessName={overview?.merchant.business_name}
        accountStatus={overview?.merchant.kyc_status}
        loading={booting}
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
          // An em dash, never a zero. "You have nothing" and "we could
          // not ask" are different statements, and the first sends a
          // merchant looking for missing money.
          value={overview ? formatCurrency(overview.available_balance, currency) : "—"}
          caption={booting ? "Loading…" : overviewError ? "Could not load" : "Current balance"}
        />
        <KpiCard
          icon="payments"
          label="Successful Collections"
          value={loading || error || !report ? "—" : formatCurrency(report.successful_collections, currency)}
          caption={loading ? "Loading…" : error ? "Could not load" : `${report?.successful_count ?? 0} payments`}
        />
        {/* Average payment, where "Fees Paid" used to be. The merchant
            portal is not the place to show a business a running total of
            what the platform has charged it; the figure is also gone
            from the API response, so it cannot be read out of the
            payload either. Per-payment fees remain on the transaction,
            wallet-ledger and payout rows, which is where a merchant
            needs them to reconcile. */}
        <KpiCard
          icon="receipt_long"
          label="Average Payment"
          value={loading || error || !report ? "—" : formatCurrency(report.average_payment, currency)}
          caption={loading ? "Loading…" : error ? "Could not load" : "Per successful payment"}
        />
        <KpiCard
          icon="hourglass_top"
          label="Pending Collections"
          value={loading || error || !report ? "—" : formatCurrency(report.pending_collections, currency)}
          caption={loading ? "Loading…" : error ? "Could not load" : `${report?.pending_count ?? 0} in flight`}
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
            <div className="flex gap-6 sm:gap-8 min-w-0">
              <div>
                <p className="text-xs text-on-surface-variant">Available</p>
                <p className="text-base sm:text-lg font-bold text-on-surface tabular-nums break-words">
                  {formatCurrency(payoutWallet.available, payoutWallet.currency)}
                </p>
              </div>
              <div>
                <p className="text-xs text-on-surface-variant">Reserved</p>
                <p className="text-base sm:text-lg font-bold text-on-surface tabular-nums break-words">
                  {formatCurrency(payoutWallet.reserved, payoutWallet.currency)}
                </p>
              </div>
            </div>
          </div>
        </Card>
      )}
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
