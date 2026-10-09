/** Reports — the headline figures, and a statement emailed on request.
 *
 * Two different things, deliberately kept apart:
 *
 *   - The totals below are fields from /v1/merchant/overview, printed as
 *     sent.
 *   - A **report** is a statement a merchant files or forwards. The
 *     backend builds it over a date range and emails it as a PDF to the
 *     account's own address — the same endpoint and the same PDF the web
 *     portal's Reports page produces. It is not downloaded here: the
 *     account email always receives it, so a report about an account's
 *     money cannot end up only on one person's phone.
 *
 * For raw rows rather than a statement, the Transactions and Wallet
 * screens export CSV directly on the device.
 */

import { useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";

import { ApiError, REPORT_TYPES, ReportType, api } from "../../src/api/client";
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
import { colors, formatTzs, radius, spacing, typography } from "../../src/theme";

/** Ranges the backend will accept — it caps a report at 366 days. Dates
 * are computed in the device's own timezone, which for a Tanzanian
 * merchant is the timezone the figures are reported in. */
const RANGES = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
  { label: "Last 365 days", days: 365 },
] as const;

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - (days - 1));
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export default function ReportsScreen() {
  const { data, error, loading, refreshing, refresh, reload } = useApi(() => api.overview());

  const [reportType, setReportType] = useState<ReportType>("TRANSACTIONS_SUMMARY");
  const [days, setDays] = useState<number>(30);
  const [sending, setSending] = useState(false);
  const [sentTo, setSentTo] = useState<string[] | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);

  async function send() {
    setSending(true);
    setSendError(null);
    setSentTo(null);
    try {
      const result = await api.generateReport({
        report_type: reportType,
        start_date: isoDaysAgo(days),
        end_date: today(),
      });
      if (result.row_count === 0) {
        Alert.alert(
          "Nothing in that range",
          "The report was sent, but it has no rows for the dates you chose.",
        );
      }
      // The server echoes back exactly who it emailed, so the merchant
      // sees the addresses rather than trusting that "sent" meant the
      // right ones.
      setSentTo(result.emailed_to);
    } catch (err) {
      setSendError(
        err instanceof ApiError
          ? err.message
          : "Couldn't generate the report. Check your connection and try again.",
      );
    } finally {
      setSending(false);
    }
  }

  if (loading)
    return (
      <AppScreen>
        <LoadingState />
      </AppScreen>
    );
  if (error)
    return (
      <AppScreen>
        <ErrorState message={error} onRetry={reload} />
      </AppScreen>
    );
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

      <SectionHeader title="Email a statement" />
      <AppCard style={s.form}>
        <Text style={s.label}>REPORT</Text>
        <View style={s.chips}>
          {REPORT_TYPES.map((option) => {
            const active = option.type === reportType;
            return (
              <Pressable
                key={option.type}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                onPress={() => {
                  setReportType(option.type);
                  setSentTo(null);
                  setSendError(null);
                }}
                style={[s.chip, active && s.chipActive]}
              >
                <Text style={[s.chipText, active && s.chipTextActive]}>{option.label}</Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={s.label}>PERIOD</Text>
        <View style={s.chips}>
          {RANGES.map((range) => {
            const active = range.days === days;
            return (
              <Pressable
                key={range.days}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                onPress={() => {
                  setDays(range.days);
                  setSentTo(null);
                  setSendError(null);
                }}
                style={[s.chip, active && s.chipActive]}
              >
                <Text style={[s.chipText, active && s.chipTextActive]}>{range.label}</Text>
              </Pressable>
            );
          })}
        </View>

        {sendError ? <Text style={s.error}>{sendError}</Text> : null}
        {sentTo ? <Text style={s.sent}>Sent to {sentTo.join(", ")}.</Text> : null}

        <PrimaryButton label="Email me this report" onPress={() => void send()} loading={sending} />

        <Text style={s.note}>
          Arrives as a PDF attached to an email, at your account address. For raw rows, use Export CSV on
          the Transactions or Wallet screen.
        </Text>
      </AppCard>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", gap: spacing.md },
  form: { gap: spacing.sm },
  label: { ...typography.caption, color: colors.onSurfaceVariant, letterSpacing: 0.5, marginTop: spacing.sm },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.outlineVariant,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { ...typography.label, color: colors.onSurface },
  chipTextActive: { color: colors.onPrimary },
  error: { ...typography.body, color: colors.error },
  sent: { ...typography.body, color: colors.success },
  note: { ...typography.caption, color: colors.onSurfaceVariant },
});
