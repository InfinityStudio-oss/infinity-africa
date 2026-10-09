/** Reports — the headline figures, with the detail left on the web.
 *
 * Every number here is a field from /v1/merchant/overview, printed as
 * sent. Downloadable statements and date-range exports stay in the
 * portal: a settlement statement is a document a merchant files, not
 * something to read on a phone.
 */

import { StyleSheet, Text, View } from "react-native";

import { api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import {
  AppCard,
  AppScreen,
  ErrorState,
  LoadingState,
  SectionHeader,
  StatCard,
} from "../../src/components";
import { colors, formatTzs, spacing, typography } from "../../src/theme";

export default function ReportsScreen() {
  const { data, error, loading, refreshing, refresh, reload } = useApi(() => api.overview());

  if (loading) return <AppScreen><LoadingState /></AppScreen>;
  if (error) return <AppScreen><ErrorState message={error} onRetry={reload} /></AppScreen>;
  if (!data) return null;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeader title="Lifetime" />
      <View style={s.row}>
        <StatCard label="Total collected" value={formatTzs(data.total_collections)} />
        <StatCard label="Total fees" value={formatTzs(data.total_fees_charged)} />
      </View>

      <SectionHeader title="Today" />
      <View style={s.row}>
        <StatCard label="Collected" value={formatTzs(data.collections_today)} />
        <StatCard label="Withdrawn" value={formatTzs(data.withdrawals_today)} />
      </View>

      <SectionHeader title="Outstanding" />
      <View style={s.row}>
        <StatCard label="Pending transactions" value={String(data.pending_transactions)} />
        <StatCard label="Unpaid invoices" value={String(data.unpaid_invoices)} />
      </View>

      <AppCard style={s.notice}>
        <Text style={s.noticeTitle}>Need a statement?</Text>
        <Text style={s.noticeBody}>
          Date-range reports and CSV exports are in the web portal under Reports. These figures are
          InfinityPay’s own totals, not a calculation made on this device.
        </Text>
      </AppCard>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", gap: spacing.md },
  notice: { backgroundColor: colors.surfaceLow, gap: spacing.xs, marginTop: spacing.sm },
  noticeTitle: { ...typography.heading, color: colors.onSurface },
  noticeBody: { ...typography.body, color: colors.onSurfaceVariant },
});
