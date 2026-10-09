/** Withdrawals — their status, and what one would cost.
 *
 * Read-and-quote only, deliberately. A withdrawal is created through the
 * same request → one-time code → Super Admin approval chain as on the
 * web, and this template does not reimplement any link in it.
 *
 * The breakdown below is the server's own, from
 * /v1/merchant/withdrawals/quote. Nothing here multiplies an amount by a
 * rate: the quote endpoint applies the merchant's pricing rules, and the
 * real withdrawal recalculates them again server-side rather than
 * trusting whatever a client was shown.
 */

import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { ApiError, DESTINATION_OPTIONS, FeeBreakdown, Withdrawal, api } from "../../src/api/client";
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
  StatusBadge,
  formatDate,
  humanise,
} from "../../src/components";
import { colors, formatTzs, radius, spacing, typography } from "../../src/theme";

/** The fields worth showing a merchant, in the order they read: what they
 * asked for, what it costs, what leaves the wallet, what arrives. The
 * response carries more (pricing rule ids, flags) that only matters to
 * support. */
const QUOTE_LINES: { key: keyof FeeBreakdown; label: string }[] = [
  { key: "withdrawal_amount", label: "Withdrawal amount" },
  { key: "total_charges", label: "Total charges" },
  { key: "total_reserved_amount", label: "Deducted from wallet" },
  { key: "recipient_net_amount", label: "Recipient receives" },
];

export default function WithdrawalsScreen() {
  const { data, error, loading, refreshing, refresh, reload } = useApi(() =>
    api.withdrawals({ pageSize: 25 }),
  );

  const [amount, setAmount] = useState("");
  const [phone, setPhone] = useState("");
  const [destination, setDestination] = useState<string>(DESTINATION_OPTIONS[0].code);
  const [quote, setQuote] = useState<FeeBreakdown | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [quoting, setQuoting] = useState(false);

  const selected = DESTINATION_OPTIONS.find((option) => option.code === destination);

  function clearQuote() {
    setQuote(null);
    setQuoteError(null);
  }

  async function getQuote() {
    if (!selected) return;
    setQuoting(true);
    setQuoteError(null);
    setQuote(null);
    try {
      setQuote(
        await api.withdrawalQuote({
          // Sent as typed. Parsing to a float here and back is the one
          // place this app could invent a different amount from the one
          // the merchant meant.
          amount: amount.trim(),
          method: selected.method,
          destination_code: selected.code,
          destination_identifier: phone.trim(),
        }),
      );
    } catch (err) {
      setQuoteError(
        err instanceof ApiError
          ? err.message
          : "Couldn't get a quote. Check your connection and try again.",
      );
    } finally {
      setQuoting(false);
    }
  }

  const canQuote = amount.trim().length > 0 && phone.trim().length > 0;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <SectionHeader title="What a withdrawal costs" />
      <AppCard style={s.quoteCard}>
        <Text style={s.label}>Send to</Text>
        <View style={s.chips}>
          {DESTINATION_OPTIONS.map((option) => {
            const active = option.code === destination;
            return (
              <Pressable
                key={option.code}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                onPress={() => {
                  setDestination(option.code);
                  clearQuote();
                }}
                style={[s.chip, active && s.chipActive]}
              >
                <Text style={[s.chipText, active && s.chipTextActive]}>{option.label}</Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={s.label}>Phone number</Text>
        <TextInput
          style={s.input}
          value={phone}
          onChangeText={(next) => {
            setPhone(next);
            clearQuote();
          }}
          keyboardType="phone-pad"
          placeholder="07XX XXX XXX"
          placeholderTextColor={colors.outline}
          autoCorrect={false}
        />

        <Text style={s.label}>Amount (TZS)</Text>
        <TextInput
          style={s.input}
          value={amount}
          onChangeText={(next) => {
            setAmount(next);
            clearQuote();
          }}
          keyboardType="decimal-pad"
          placeholder="0"
          placeholderTextColor={colors.outline}
          inputMode="decimal"
        />

        <PrimaryButton label="Get quote" onPress={getQuote} loading={quoting} disabled={!canQuote} />

        {quoteError ? <Text style={s.quoteError}>{quoteError}</Text> : null}

        {quote ? (
          <View style={s.quoteLines}>
            {QUOTE_LINES.map((line) => (
              <View key={line.key} style={s.quoteLine}>
                <Text style={s.quoteKey}>{line.label}</Text>
                <Text style={s.quoteValue}>{formatTzs(quote[line.key])}</Text>
              </View>
            ))}
            <Text style={s.note}>Quoted on the {humanise(quote.channel)} channel by InfinityPay.</Text>
          </View>
        ) : null}

        <Text style={s.note}>
          A quote reserves nothing and creates nothing. To request the payout, sign in to the web portal
          — it still goes through the same one-time code and Super Admin approval.
        </Text>
      </AppCard>

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
                meta={`${withdrawal.bank_name ?? humanise(withdrawal.destination_code)} · ${
                  withdrawal.destination_name
                } · ${formatDate(withdrawal.created_at)}`}
                right={<StatusBadge status={withdrawal.status} />}
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
    </AppScreen>
  );
}

const s = StyleSheet.create({
  quoteCard: { gap: spacing.sm },
  label: { ...typography.label, color: colors.onSurfaceVariant, marginTop: spacing.sm },
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
  input: {
    ...typography.body,
    fontSize: 16,
    color: colors.onSurface,
    backgroundColor: colors.surfaceLow,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.outlineVariant,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    minHeight: 48,
  },
  quoteError: { ...typography.body, color: colors.error },
  quoteLines: {
    gap: spacing.sm,
    paddingTop: spacing.md,
    marginTop: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.outlineVariant,
  },
  quoteLine: { flexDirection: "row", justifyContent: "space-between", gap: spacing.md },
  quoteKey: { ...typography.body, color: colors.onSurfaceVariant },
  quoteValue: { ...typography.label, color: colors.onSurface, fontVariant: ["tabular-nums"] },
  note: { ...typography.caption, color: colors.onSurfaceVariant },
});
