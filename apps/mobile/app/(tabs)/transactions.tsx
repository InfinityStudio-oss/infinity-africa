/** Transactions — what came in, what it cost, and what settled.
 *
 * Search runs on the server, against the transaction reference. There is
 * no status filter here because the endpoint has none: it is paginated,
 * and filtering the 25 rows the phone happens to hold would report "not
 * found" for a transaction sitting on the next page.
 */

import { useEffect, useState } from "react";
import { StyleSheet, Text, TextInput } from "react-native";

import { Transaction, api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import {
  AppCard,
  AppScreen,
  EmptyState,
  ErrorState,
  ListRow,
  LoadingState,
  StatusBadge,
  formatDate,
  humanise,
} from "../../src/components";
import { colors, formatTzs, maskPhone, radius, spacing, typography } from "../../src/theme";

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

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
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

      {loading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {!loading && !error ? (
        data && data.length > 0 ? (
          <AppCard>
            {data.map((txn: Transaction) => (
              <ListRow
                key={txn.id}
                title={formatTzs(txn.gross_amount)}
                meta={`${txn.reference} · ${humanise(txn.method)} · ${formatDate(txn.created_at)}`}
                right={<StatusBadge status={txn.status} />}
                rightMeta={`Net ${formatTzs(txn.net_amount)}${
                  txn.customer_phone ? ` · ${maskPhone(txn.customer_phone)}` : ""
                }`}
              />
            ))}
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
