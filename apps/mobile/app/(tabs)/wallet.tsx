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
  PrimaryButton,
  SectionHeader,
  StatCard,
  StatusBadge,
  formatDate,
  humanise,
} from "../../src/components";
import { colors, formatTzs, spacing, typography } from "../../src/theme";

export default function WalletScreen() {
  const overview = useApi(() => api.overview());
  const ledger = useApi(() => api.walletLedger({ pageSize: 25 }));

  const refreshing = overview.refreshing || ledger.refreshing;
  const refresh = () => {
    void overview.refresh();
    void ledger.refresh();
  };

  const [exporting, setExporting] = useState(false);

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
              return (
                <ListRow
                  key={entry.id}
                  title={`${credit ? "+" : "−"}${formatTzs(entry.amount)}`}
                  meta={`${entry.description ?? humanise(entry.method)} · ${formatDate(entry.date)}`}
                  right={entry.status ? <StatusBadge status={entry.status} /> : undefined}
                  rightMeta={`Balance ${formatTzs(entry.balance_after)}`}
                />
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
  statRow: { flexDirection: "row", gap: spacing.md },
  note: { ...typography.caption, color: colors.onSurfaceVariant, textAlign: "center", marginTop: spacing.sm },
});
