/** Transactions — what came in, what it cost, and what settled.
 *
 * Search runs on the server, against the transaction reference. There is
 * no status filter here because the endpoint has none: it is paginated,
 * and filtering the 25 rows the phone happens to hold would report "not
 * found" for a transaction sitting on the next page.
 */

import { useEffect, useState } from "react";
import { Alert, StyleSheet, Text, TextInput, View } from "react-native";

import { Transaction, api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import { ExportError, exportFilename, shareCsv, transactionsToCsv } from "../../src/export/csv";
import {
  AppCard,
  AppScreen,
  EmptyState,
  ErrorState,
  ListRow,
  LoadingState,
  MoneyBreakdown,
  PrimaryButton,
  StatusBadge,
  formatDate,
  humanise,
} from "../../src/components";
import {
  colors,
  formatTzs,
  formatTzsOrUnavailable,
  maskPhone,
  radius,
  spacing,
  typography,
} from "../../src/theme";

export default function TransactionsScreen() {
  const [term, setTerm] = useState("");
  const [search, setSearch] = useState("");

  // Debounced so typing a reference is one request, not one per letter.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(term.trim()), 400);
    return () => clearTimeout(timer);
  }, [term]);

  const { data, error, loading, refreshing, refresh, reload } = useApi(
    () => api.transactions({ search: search || undefined, pageSize: 25 }),
    [search],
  );

  const [exporting, setExporting] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  /** Exports the rows this screen is holding, not the whole account. The
   * share dialog names the count so a page is never mistaken for a full
   * statement; the emailed PDF report on the Reports screen covers a date
   * range properly. */
  async function exportCsv() {
    if (!data || data.length === 0) return;
    setExporting(true);
    try {
      await shareCsv(
        exportFilename("transactions"),
        transactionsToCsv(data),
        `InfinityPay transactions (${data.length} rows)`,
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

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <View style={s.toolbar}>
        <TextInput
          style={s.search}
          value={term}
          onChangeText={setTerm}
          placeholder="Search by reference"
          placeholderTextColor={colors.outline}
          autoCapitalize="characters"
          autoCorrect={false}
          returnKeyType="search"
        />
        <PrimaryButton
          label="Export CSV"
          variant="outline"
          onPress={() => void exportCsv()}
          loading={exporting}
          disabled={!data || data.length === 0}
        />
      </View>

      {loading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {!loading && !error ? (
        data && data.length > 0 ? (
          <AppCard>
            <Text style={s.tapHint}>
              Tap a line for its opening balance, charge and closing balance.
            </Text>
            {data.map((txn: Transaction) => {
              const open = expanded === txn.id;
              return (
                <View key={txn.id}>
                  <ListRow
                    title={formatTzs(txn.gross_amount)}
                    meta={`${txn.reference} · ${humanise(txn.method)} · ${formatDate(
                      txn.created_at,
                    )}`}
                    right={<StatusBadge status={txn.status} />}
                    rightMeta={`Net ${formatTzs(txn.net_amount)}${
                      txn.customer_phone ? ` · ${maskPhone(txn.customer_phone)}` : ""
                    }`}
                    onPress={() => setExpanded(open ? null : txn.id)}
                  />
                  {open ? (
                    <MoneyBreakdown
                      lines={[
                        // Nullable on transactions: null for rows created
                        // before the column existed, or with no
                        // wallet-affecting leg. Shown as "Not available"
                        // rather than backfilled with a derived figure.
                        {
                          label: "Opening balance",
                          value: formatTzsOrUnavailable(txn.balance_before),
                        },
                        { label: "Amount", value: formatTzs(txn.gross_amount) },
                        { label: "Charge", value: formatTzs(txn.fee_amount) },
                        { label: "Net", value: formatTzs(txn.net_amount) },
                        {
                          label: "Closing balance",
                          value: formatTzsOrUnavailable(txn.balance_after),
                          strong: true,
                        },
                      ]}
                    />
                  ) : null}
                </View>
              );
            })}
          </AppCard>
        ) : (
          <EmptyState
            title={search ? "Nothing matches that reference" : "No transactions"}
            message={
              search
                ? "Check the reference and try again."
                : "Payments collected through your links, invoices or API will appear here."
            }
          />
        )
      ) : null}

      {data && data.length === 25 ? (
        <Text style={s.hint}>Showing the 25 most recent. The web portal has the full history.</Text>
      ) : null}
    </AppScreen>
  );
}

const s = StyleSheet.create({
  tapHint: { ...typography.caption, color: colors.onSurfaceVariant, paddingBottom: spacing.xs },
  toolbar: { gap: spacing.sm },
  search: {
    ...typography.body,
    fontSize: 16,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.outlineVariant,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    minHeight: 44,
  },
  hint: { ...typography.caption, color: colors.onSurfaceVariant, textAlign: "center" },
});
