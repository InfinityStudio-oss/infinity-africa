/** Raising a withdrawal — the same three steps as the web portal.
 *
 *   1. Fill in the form, then check the balance. The check is a server
 *      call that creates nothing.
 *   2. Review exactly what is about to be submitted. Still no withdrawal,
 *      still no code: only a provider lookup for the recipient's name.
 *   3. Ask for a code, then enter it. The withdrawal is created by the
 *      verify step and only ever as PENDING_ADMIN_APPROVAL — a Super Admin
 *      approving it on the web is what reaches the provider.
 *
 * **Charges are deliberately absent.** A merchant withdrawal is not
 * charged, and a "TZS 0.00 fee" line invites the question of when it might
 * not be. The quote call is still made, because it is the server's own
 * validation of the amount and destination and it reports what the wallet
 * must cover — but what the merchant is told is that they receive the full
 * amount, which is the same thing the portal says.
 *
 * Nothing here decides anything. The amount is sent as typed, the fee is
 * the server's, the balance check is the server's, and the approval is a
 * person's.
 */

import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import {
  ApiError,
  DESTINATIONS_BY_METHOD,
  DISBURSEMENT_METHODS,
  DisbursementMethod,
  FeeBreakdown,
  WithdrawalOtpChallenge,
  api,
  destinationLabel,
  methodLabel,
} from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import {
  AppCard,
  AppScreen,
  LoadingState,
  PrimaryButton,
  SectionHeader,
} from "../../src/components";
import { colors, formatTzs, radius, spacing, typography } from "../../src/theme";

type Step = "form" | "review" | "otp" | "done";

function errorMessage(err: unknown, fallback: string): string {
  // The backend's own wording, always. These messages are written for
  // merchants — "withdrawals are paused", "an open fraud alert must be
  // cleared first", "insufficient balance" — and replacing one with a
  // generic line is how a real 409 once became "Something went wrong".
  return err instanceof ApiError ? err.message : fallback;
}

export default function NewWithdrawalScreen() {
  const router = useRouter();

  const overview = useApi(() => api.overview());
  const membership = useApi(() => api.membership());

  const [step, setStep] = useState<Step>("form");
  const [method, setMethod] = useState<DisbursementMethod>("SELCOM_PESA");
  const [destinationCode, setDestinationCode] = useState("SELCOM");
  const [identifier, setIdentifier] = useState("");
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");

  const [quote, setQuote] = useState<FeeBreakdown | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  /** What the current quote was taken for. Any edit to the method,
   * destination or amount makes it stale — the merchant must never submit
   * against a check that was run on different numbers. */
  const [quotedFor, setQuotedFor] = useState<string | null>(null);

  const [recipientName, setRecipientName] = useState<string | null>(null);
  const [resolvingName, setResolvingName] = useState(false);

  const [challenge, setChallenge] = useState<WithdrawalOtpChallenge | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  const balance = overview.data?.available_balance ?? "0";
  const isBank = method === "BANK_ACCOUNT";
  const quoteKey = `${method}|${destinationCode}|${amount.trim()}`;
  const quoteIsStale = quotedFor !== quoteKey;
  const exceedsBalance =
    quote !== null && !quoteIsStale && Number(quote.total_reserved_amount) > Number(balance);
  const isAdmin = membership.data?.role === "MERCHANT_ADMIN";

  // Resend cooldown. The server sets the interval; this only counts it
  // down so the button does not invite a request that would be refused.
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown((n) => (n <= 1 ? 0 : n - 1)), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  const invalidateQuote = useCallback(() => {
    setQuote(null);
    setQuotedFor(null);
    setQuoteError(null);
    setError(null);
  }, []);

  function chooseMethod(next: DisbursementMethod) {
    setMethod(next);
    // Each method has its own destinations; keeping the old one would send
    // a bank code with a mobile-money method.
    // Every method has at least one entry, so the fallback is
    // unreachable - it is here because the table is a plain array and the
    // compiler cannot know that.
    setDestinationCode(DESTINATIONS_BY_METHOD[next][0]?.code ?? "");
    setIdentifier("");
    invalidateQuote();
  }

  async function checkBalance() {
    setQuoteError(null);
    if (!amount.trim() || Number(amount) <= 0) {
      setQuoteError("Enter an amount first.");
      return;
    }
    if (!identifier.trim()) {
      setQuoteError(isBank ? "Enter the account number first." : "Enter the phone number first.");
      return;
    }
    setQuoting(true);
    try {
      setQuote(
        await api.withdrawalQuote({
          amount: amount.trim(),
          method,
          destination_code: destinationCode,
          destination_identifier: identifier.trim(),
        }),
      );
      setQuotedFor(quoteKey);
    } catch (err) {
      setQuoteError(errorMessage(err, "Couldn't check your balance. Try again."));
    } finally {
      setQuoting(false);
    }
  }

  /** Opens the review. Deliberately makes no request: the merchant sees
   * exactly what they are about to submit before anything is sent and
   * before a code lands in their inbox. */
  function openReview() {
    setError(null);
    if (!quote || quoteIsStale) {
      setError("Check your balance before confirming this withdrawal.");
      return;
    }
    if (exceedsBalance) {
      setError("This amount exceeds your available balance.");
      return;
    }
    setStep("review");

    // Fire-and-forget. A slow or failed provider lookup must not hold up
    // the merchant, and the review already reads "Name not available" from
    // a null name, which is the right thing to show either way.
    setRecipientName(null);
    setResolvingName(true);
    void api
      .resolveWithdrawalRecipient({
        method,
        destination_code: destinationCode,
        destination_identifier: identifier.trim(),
      })
      .then(setRecipientName)
      .catch(() => setRecipientName(null))
      .finally(() => setResolvingName(false));
  }

  async function sendCode() {
    setError(null);
    setBusy(true);
    try {
      const next = await api.createWithdrawal({
        method,
        amount: amount.trim(),
        destination_code: destinationCode,
        destination_identifier: identifier.trim(),
        description: notes.trim() || null,
      });
      setChallenge(next);
      setCooldown(next.resend_cooldown_seconds);
      setCode("");
      setStep("otp");
    } catch (err) {
      setError(errorMessage(err, "Couldn't request a verification code. Try again."));
      // Back to the form with everything still filled in — nobody should
      // have to retype a withdrawal because a request failed.
      setStep("form");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    if (!challenge) return;
    setError(null);
    setBusy(true);
    try {
      await api.verifyWithdrawal(challenge.challenge_id, code.trim());
      setStep("done");
    } catch (err) {
      setError(errorMessage(err, "Couldn't verify that code. Try again."));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    if (!challenge) return;
    setError(null);
    setBusy(true);
    try {
      const next = await api.resendWithdrawalOtp(challenge.challenge_id);
      setChallenge(next);
      setCooldown(next.resend_cooldown_seconds);
      setCode("");
    } catch (err) {
      setError(errorMessage(err, "Couldn't send a new code. Try again."));
    } finally {
      setBusy(false);
    }
  }

  if (overview.loading || membership.loading) {
    return (
      <AppScreen>
        <LoadingState />
      </AppScreen>
    );
  }

  // --- Submitted ---------------------------------------------------------

  if (step === "done") {
    return (
      <AppScreen>
        <AppCard style={s.block}>
          <Text style={s.successTitle}>Withdrawal submitted</Text>
          <Text style={s.body}>
            {formatTzs(amount)} to {destinationLabel(destinationCode)} is now waiting for approval. You
            will be notified once it has been reviewed.
          </Text>
          <Text style={s.note}>
            Every withdrawal is approved by an InfinityPay administrator before any money moves. You can
            follow its status on the Withdrawals screen.
          </Text>
          <PrimaryButton label="Done" onPress={() => router.back()} />
        </AppCard>
      </AppScreen>
    );
  }

  // --- Verification code ------------------------------------------------

  if (step === "otp" && challenge) {
    return (
      <AppScreen>
        <AppCard style={s.block}>
          <Text style={s.stepTitle}>Enter the verification code</Text>
          <Text style={s.body}>
            We sent a 6-digit code to {challenge.masked_email}. It is needed to submit this withdrawal.
          </Text>

          <TextInput
            style={s.codeInput}
            value={code}
            onChangeText={(next) => setCode(next.replace(/\D/g, "").slice(0, 6))}
            keyboardType="number-pad"
            inputMode="numeric"
            placeholder="______"
            placeholderTextColor={colors.outline}
            maxLength={6}
            autoFocus
            textAlign="center"
            // Never offered to a password manager, and never pre-filled:
            // this code authorises a payout.
            autoComplete="one-time-code"
          />

          {error ? <Text style={s.error}>{error}</Text> : null}

          <PrimaryButton
            label="Submit withdrawal"
            onPress={() => void verify()}
            loading={busy}
            disabled={code.length !== 6}
          />
          <PrimaryButton
            label={cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
            variant="outline"
            onPress={() => void resend()}
            disabled={busy || cooldown > 0}
          />
          <Pressable
            accessibilityRole="button"
            onPress={() => {
              // The challenge is abandoned, not cancelled. It holds no
              // funds and created nothing, so leaving it is inert.
              setStep("form");
              setChallenge(null);
              setError(null);
            }}
          >
            <Text style={s.link}>Back to the form</Text>
          </Pressable>

          <Text style={s.note}>
            You have up to {challenge.max_attempts} attempts. Nobody from InfinityPay will ever ask you
            for this code.
          </Text>
        </AppCard>
      </AppScreen>
    );
  }

  // --- Review -----------------------------------------------------------

  if (step === "review") {
    const destLabel = destinationLabel(destinationCode);
    const methLabel = methodLabel(method);
    return (
      <AppScreen>
        <AppCard style={s.block}>
          <Text style={s.stepTitle}>Review your withdrawal</Text>
          <Text style={s.body}>
            We’ll send a verification code to your email before submitting this request.
          </Text>

          <View style={s.rows}>
            <Row
              label="Recipient name"
              value={recipientName ?? (resolvingName ? "Checking…" : "Name not available")}
              muted={!recipientName}
            />
            <Row label="Withdraw to" value={methLabel} />
            {/* Only when it says something the method line did not — for
                Selcom Pesa the two are the same name. */}
            {destLabel !== methLabel ? <Row label="Destination" value={destLabel} /> : null}
            <Row label={isBank ? "Account number" : "Phone number"} value={identifier.trim()} mono />
            {notes.trim() ? <Row label="Note" value={notes.trim()} /> : null}
            <View style={s.divider} />
            <Row label="Amount" value={formatTzs(amount)} strong />
            <Row label="Available balance" value={formatTzs(balance)} />
          </View>

          {error ? <Text style={s.error}>{error}</Text> : null}

          <PrimaryButton
            label="Send verification code"
            onPress={() => void sendCode()}
            loading={busy}
          />
          <PrimaryButton
            label="Back"
            variant="outline"
            onPress={() => setStep("form")}
            disabled={busy}
          />
        </AppCard>
      </AppScreen>
    );
  }

  // --- Form -------------------------------------------------------------

  return (
    <AppScreen>
      {!isAdmin ? (
        <AppCard style={s.warning}>
          <Text style={s.warningTitle}>Only an account admin can withdraw</Text>
          <Text style={s.warningBody}>
            Your role on this account is {membership.data?.role?.replace(/_/g, " ").toLowerCase() ?? "unknown"}.
            Ask an admin on your business to raise the withdrawal.
          </Text>
        </AppCard>
      ) : null}

      <SectionHeader title="Withdraw to" />
      <View style={s.methods}>
        {DISBURSEMENT_METHODS.map((option) => {
          const active = option.method === method;
          return (
            <Pressable
              key={option.method}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => chooseMethod(option.method)}
              style={[s.methodCard, active && s.methodCardActive]}
            >
              <Text style={[s.methodLabel, active && s.methodLabelActive]}>{option.label}</Text>
              {option.recommended ? (
                <Text style={[s.methodBadge, active && s.methodLabelActive]}>Recommended</Text>
              ) : null}
            </Pressable>
          );
        })}
      </View>

      <AppCard style={s.block}>
        <Text style={s.label}>{isBank ? "Bank" : "Provider"}</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
          {DESTINATIONS_BY_METHOD[method].map((option) => {
            const active = option.code === destinationCode;
            return (
              <Pressable
                key={option.code}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                onPress={() => {
                  setDestinationCode(option.code);
                  invalidateQuote();
                }}
                style={[s.chip, active && s.chipActive]}
              >
                <Text style={[s.chipText, active && s.chipTextActive]}>{option.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>

        <Text style={s.label}>{isBank ? "Account number" : "Phone number"}</Text>
        <TextInput
          style={s.input}
          value={identifier}
          onChangeText={(next) => {
            setIdentifier(next);
            invalidateQuote();
          }}
          keyboardType={isBank ? "number-pad" : "phone-pad"}
          placeholder={isBank ? "0123456789" : "07XX XXX XXX"}
          placeholderTextColor={colors.outline}
          autoCorrect={false}
        />

        <Text style={s.label}>Amount (TZS)</Text>
        <TextInput
          style={s.input}
          value={amount}
          onChangeText={(next) => {
            setAmount(next);
            invalidateQuote();
          }}
          keyboardType="decimal-pad"
          inputMode="decimal"
          placeholder="0"
          placeholderTextColor={colors.outline}
        />

        <Text style={s.label}>Note (optional)</Text>
        <TextInput
          style={s.input}
          value={notes}
          onChangeText={setNotes}
          placeholder="What this payout is for"
          placeholderTextColor={colors.outline}
          maxLength={140}
        />

        <View style={s.rows}>
          <Row label="Available balance" value={formatTzs(balance)} />
          {quote && !quoteIsStale ? (
            <>
              <View style={s.divider} />
              <Row label="Withdrawal amount" value={formatTzs(quote.withdrawal_amount)} strong />
              {/* The portal's own line. Merchant withdrawals are not
                  charged, so this is the whole fee story. */}
              <Text style={s.fullAmount}>You receive the full amount.</Text>
              {exceedsBalance ? (
                <Text style={s.error}>This amount exceeds your available balance.</Text>
              ) : null}
            </>
          ) : (
            <Text style={s.note}>
              Enter an amount and destination, then check your balance before submitting.
            </Text>
          )}
        </View>

        {quoteError ? <Text style={s.error}>{quoteError}</Text> : null}
        {error ? <Text style={s.error}>{error}</Text> : null}

        <PrimaryButton
          label="Check balance"
          variant="outline"
          onPress={() => void checkBalance()}
          loading={quoting}
          disabled={!isAdmin}
        />
        <PrimaryButton
          label="Continue"
          onPress={openReview}
          disabled={!isAdmin || !quote || quoteIsStale || exceedsBalance}
        />
      </AppCard>

      <Text style={s.note}>
        Every withdrawal is reviewed by an InfinityPay administrator before any money moves.
      </Text>
    </AppScreen>
  );
}

function Row({
  label,
  value,
  strong,
  mono,
  muted,
}: {
  label: string;
  value: string;
  strong?: boolean;
  mono?: boolean;
  muted?: boolean;
}) {
  return (
    <View style={s.row}>
      <Text style={s.rowLabel}>{label}</Text>
      <Text
        style={[s.rowValue, strong && s.rowValueStrong, mono && s.rowValueMono, muted && s.rowValueMuted]}
      >
        {value}
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  block: { gap: spacing.sm },
  stepTitle: { ...typography.title, color: colors.onSurface },
  successTitle: { ...typography.title, color: colors.success },
  body: { ...typography.body, color: colors.onSurfaceVariant },
  label: { ...typography.label, color: colors.onSurfaceVariant, marginTop: spacing.sm },
  note: { ...typography.caption, color: colors.onSurfaceVariant },
  error: { ...typography.body, color: colors.error },
  link: { ...typography.label, color: colors.primary, textAlign: "center", paddingVertical: spacing.sm },
  fullAmount: { ...typography.caption, color: colors.success },

  methods: { flexDirection: "row", gap: spacing.sm },
  methodCard: {
    flex: 1,
    gap: 2,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.outlineVariant,
    backgroundColor: colors.surface,
    alignItems: "center",
  },
  methodCardActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  methodLabel: { ...typography.label, color: colors.onSurface, textAlign: "center" },
  methodLabelActive: { color: colors.onPrimary },
  methodBadge: { ...typography.caption, color: colors.success },

  chips: { gap: spacing.sm, paddingVertical: spacing.xs },
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
  codeInput: {
    ...typography.display,
    color: colors.onSurface,
    backgroundColor: colors.surfaceLow,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.outlineVariant,
    paddingVertical: spacing.md,
    letterSpacing: 8,
    fontVariant: ["tabular-nums"],
  },

  rows: { gap: spacing.sm, paddingTop: spacing.sm },
  row: { flexDirection: "row", justifyContent: "space-between", gap: spacing.md },
  rowLabel: { ...typography.body, color: colors.onSurfaceVariant },
  rowValue: { ...typography.label, color: colors.onSurface, flexShrink: 1, textAlign: "right" },
  rowValueStrong: { ...typography.heading, color: colors.onSurface },
  rowValueMono: { fontVariant: ["tabular-nums"] },
  rowValueMuted: { color: colors.onSurfaceVariant, fontStyle: "italic" },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: colors.outlineVariant },

  warning: { backgroundColor: colors.warningContainer, borderColor: colors.warningContainer, gap: spacing.xs },
  warningTitle: { ...typography.heading, color: colors.warning },
  warningBody: { ...typography.body, color: colors.warning },
});
