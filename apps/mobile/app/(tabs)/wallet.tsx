/** Wallet — the balance, and the ledger that explains it.
 *
 * Opening and closing balances are the server's figures, printed as
 * sent. Nothing is added up here: a running total computed on a phone
 * that disagreed with the ledger would be worse than no total at all.
 */

import { useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";

import { api, LedgerEntry } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import { ExportError, exportFilename, ledgerToCsv, shareCsv } from "../../src/export/csv";
import {
  AppCard,
  AppScreen,
  EmptyState,
  ErrorState,
  ListRow,
  LoadingState,
  MoneyBreakdown,
  PrimaryButton,
  SectionHeader,
  StatCard,
  StatusBadge,
  formatDate,
  humanise,
} from "../../src/components";
import { colors, formatTzs, formatTzsOrUnavailable, maskPhone, spacing, typography } from "../../src/theme";

export default function WalletScreen() {
  const overview = useApi(() => api.overview());
  const ledger = useApi(() => api.walletLedger({ pageSize: 25 }));

  const refreshing = overview.refreshing || ledger.refreshing;
  const refresh = () => {
    void overview.refresh();
    void ledger.refresh();
  };

  const [exporting, setExporting] = useState(false);
  /** Which row is showing its money columns. One at a time: this is a
   * list to scan, not a table to read all of at once. */
  const [expanded, setExpanded] = useState<string | null>(null);

  /** Exports the ledger page on screen. The web portal exports the ledger
   * as Excel from the backend over a date range; CSV built here is the
   * equivalent a phone can actually hand to another app, and the share
   * dialog states the row count so a page is not mistaken for a
   * statement. */
  async function exportCsv() {
    const entries = ledger.data;
    if (!entries || entries.length === 0) return;
    setExporting(true);
    try {
      await shareCsv(
        exportFilename("wallet-ledger"),
        ledgerToCsv(entries),
        `InfinityPay wallet ledger (${entries.length} rows)`,
      );
    } catch (err) {
      Alert.alert(
        "Couldn’t export",
        err instanceof ExportError ? err.message : "Something went wrong writing the file.",
      );
    } finally {
      setExporting(false);
    }
  }

  if (overview.loading) return <AppScreen><LoadingState /></AppScreen>;
  if (overview.error)
    return <AppScreen><ErrorState message={overview.error} onRetry={overview.reload} /></AppScreen>;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <StatCard
        label="Available balance"
        value={formatTzs(overview.data?.available_balance)}
        caption="Settled funds you can withdraw"
        tone="brand"
      />
      <View style={s.statRow}>
        <StatCard label="Total collected" value={formatTzs(overview.data?.total_collections)} />
        <StatCard label="Total fees" value={formatTzs(overview.data?.total_fees_charged)} />
      </View>

      <SectionHeader title="Wallet ledger" />
      <Text style={s.hint}>Tap a line for its opening balance, charge and closing balance.</Text>
      <PrimaryButton
        label="Export CSV"
        variant="outline"
        onPress={() => void exportCsv()}
        loading={exporting}
        disabled={!ledger.data || ledger.data.length === 0}
      />
      {ledger.loading ? <LoadingState /> : null}
      {ledger.error ? <ErrorState message={ledger.error} onRetry={ledger.reload} /> : null}

      {!ledger.loading && !ledger.error ? (
        ledger.data && ledger.data.length > 0 ? (
          <AppCard>
            {ledger.data.map((entry: LedgerEntry) => {
              const credit = entry.direction === "credit";
              const open = expanded === entry.id;
              return (
                <View key={entry.id}>
                  <ListRow
                    title={`${credit ? "+" : "−"}${formatTzs(entry.amount)}`}
                    meta={`${entry.description ?? humanise(entry.method)} · ${formatDate(entry.date)}`}
                    right={entry.status ? <StatusBadge status={entry.status} /> : undefined}
                    rightMeta={`Balance ${formatTzs(entry.balance_after)}`}
                    onPress={() => setExpanded(open ? null : entry.id)}
                  />
                  {open ? (
                    <MoneyBreakdown
                      lines={[
                        { label: "Opening balance", value: formatTzs(entry.balance_before) },
                        {
                          label: credit ? "Amount in" : "Amount out",
                          value: formatTzs(entry.amount),
                        },
                        // Nullable on the ledger - "Not available" rather
                        // than a zero the server did not send.
                        { label: "Charge", value: formatTzsOrUnavailable(entry.fee_amount) },
                        { label: "Net", value: formatTzsOrUnavailable(entry.net_amount) },
                        {
                          label: "Closing balance",
                          value: formatTzs(entry.balance_after),
                          strong: true,
                        },
                        ...(entry.reference ? [{ label: "Reference", value: entry.reference }] : []),
                        ...(entry.customer_phone
                          ? [{ label: "Customer", value: maskPhone(entry.customer_phone) }]
                          : []),
                      ]}
                    />
                  ) : null}
                </View>
              );
            })}
          </AppCard>
        ) : (
          <EmptyState
            title="No wallet movements yet"
            message="Every credit and debit on your wallet will be listed here, with the balance it left behind."
          />
        )
      ) : null}

      <Text style={s.note}>
        Balances and charges are calculated by InfinityPay, not by this app. If a figure looks wrong, it is
        wrong everywhere — tell support rather than reinstalling.
      </Text>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  hint: { ...typography.caption, color: colors.onSurfaceVariant },
  statRow: { flexDirection: "row", gap: spacing.md },
  note: { ...typography.caption, color: colors.onSurfaceVariant, textAlign: "center", marginTop: spacing.sm },
});
