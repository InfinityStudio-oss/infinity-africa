/** Home — the screen a merchant opens to answer "how much do I have?" */

import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import {
  AppCard,
  AppScreen,
  ErrorState,
  LoadingState,
  PrimaryButton,
  SectionHeader,
  StatCard,
} from "../../src/components";
import { colors, formatTzs, spacing, typography } from "../../src/theme";

export default function HomeScreen() {
  const router = useRouter();
  const { data, error, loading, refreshing, refresh, reload } = useApi(() => api.overview());

  if (loading) return <AppScreen><LoadingState /></AppScreen>;
  if (error) return <AppScreen><ErrorState message={error} onRetry={reload} /></AppScreen>;
  if (!data) return null;

  const merchant = data.merchant;
  const notActive = merchant.status !== "active";

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Text style={s.greeting}>{merchant.business_name}</Text>
      {merchant.merchant_code ? <Text style={s.code}>ID {merchant.merchant_code}</Text> : null}

      {/* Whatever the backend says about this account, shown plainly. The
          app never decides this and never works around it. */}
      {notActive ? (
        <AppCard style={s.notice}>
          <Text style={s.noticeTitle}>
            {merchant.status === "pending" ? "Account under review" : "Account not active"}
          </Text>
          <Text style={s.noticeBody}>
            {merchant.status === "pending"
              ? "Your business is being verified. You can explore the app, but collecting and withdrawing stay locked until it is approved."
              : "Collecting and withdrawing are unavailable on this account. Contact support if you think this is a mistake."}
          </Text>
        </AppCard>
      ) : null}

      <StatCard label="Available balance" value={formatTzs(data.available_balance)} tone="brand" />

      <View style={s.statRow}>
        <StatCard label="Collections today" value={formatTzs(data.collections_today)} />
        <StatCard label="Withdrawals today" value={formatTzs(data.withdrawals_today)} />
      </View>
      <View style={s.statRow}>
        <StatCard label="Active payment links" value={String(data.active_payment_links)} />
        <StatCard label="Pending transactions" value={String(data.pending_transactions)} />
      </View>

      <SectionHeader title="Quick actions" />
      <AppCard style={s.actions}>
        <PrimaryButton label="View wallet" onPress={() => router.push("/wallet")} />
        <PrimaryButton label="Transactions" variant="outline" onPress={() => router.push("/transactions")} />
        <PrimaryButton
          label="Withdraw funds"
          variant="outline"
          disabled={notActive}
          onPress={() => router.push("/withdrawals/new")}
        />
        <PrimaryButton
          label="API credentials"
          variant="outline"
          onPress={() => router.push("/more/api-credentials")}
        />
      </AppCard>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  greeting: { ...typography.display, color: colors.onSurface },
  code: { ...typography.caption, color: colors.onSurfaceVariant, marginTop: -spacing.sm },
  statRow: { flexDirection: "row", gap: spacing.md },
  notice: { backgroundColor: colors.warningContainer, borderColor: colors.warningContainer, gap: spacing.xs },
  noticeTitle: { ...typography.heading, color: colors.warning },
  noticeBody: { ...typography.body, color: colors.warning },
  actions: { gap: spacing.md },
});
