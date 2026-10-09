/** Withdrawals — your payouts and their approval status.
 *
 * The "what would this cost" calculator that used to be here is gone.
 * Merchant withdrawals are not charged, so a charges panel was answering
 * a question the product does not have, and it implied there was a fee to
 * look up. Raising a withdrawal now goes through the same three steps as
 * the web portal — see app/withdrawals/new.tsx.
 */

import { useRouter } from "expo-router";
import { StyleSheet, Text } from "react-native";

import { Withdrawal, api, destinationLabel, methodLabel } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
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
} from "../../src/components";
import { colors, formatTzs, typography } from "../../src/theme";

export default function WithdrawalsScreen() {
  const router = useRouter();
  const overview = useApi(() => api.overview());
  const { data, error, loading, refreshing, refresh, reload } = useApi(() =>
    api.withdrawals({ pageSize: 25 }),
  );

  const notActive = overview.data ? overview.data.merchant.status !== "active" : false;

  return (
    <AppScreen
      refreshing={refreshing || overview.refreshing}
      onRefresh={() => {
        void refresh();
        void overview.refresh();
      }}
    >
      <StatCard
        label="Available balance"
        value={formatTzs(overview.data?.available_balance)}
        caption="Settled funds you can withdraw"
        tone="brand"
      />

      <PrimaryButton
        label="New withdrawal"
        onPress={() => router.push("/withdrawals/new")}
        disabled={notActive}
      />
      {notActive ? (
        <Text style={s.note}>
          Withdrawals are unavailable while your account is {overview.data?.merchant.status}.
        </Text>
      ) : null}

      <SectionHeader title="Your withdrawals" />
      {loading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {!loading && !error ? (
        data && data.length > 0 ? (
          <AppCard>
            {data.map((withdrawal: Withdrawal) => (
              <ListRow
                key={withdrawal.id}
                title={formatTzs(withdrawal.amount)}
                meta={`${withdrawal.bank_name ?? destinationLabel(withdrawal.destination_code)} · ${
                  withdrawal.destination_identifier
                } · ${formatDate(withdrawal.created_at)}`}
                right={<StatusBadge status={withdrawal.status} />}
                rightMeta={methodLabel(withdrawal.method)}
              />
            ))}
          </AppCard>
        ) : (
          <EmptyState
            title="No withdrawals yet"
            message="Payouts you request will appear here with their approval status."
          />
        )
      ) : null}

      <Text style={s.note}>
        Every withdrawal is reviewed by an InfinityPay administrator before any money moves. There is no
        charge for withdrawing — you receive the full amount.
      </Text>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  note: { ...typography.caption, color: colors.onSurfaceVariant, textAlign: "center" },
});
