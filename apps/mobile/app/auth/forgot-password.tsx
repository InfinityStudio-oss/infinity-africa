/** Password reset request.
 *
 * The backend emails the link and the link opens the web portal's reset
 * form at /dashboard/reset-password, which is where the new password is
 * set. One reset flow, one place it can go wrong — and the merchant gets
 * InfinityPay's own branded email rather than Supabase's default one.
 */

import { useState } from "react";
import { StyleSheet, Text, TextInput } from "react-native";

import { requestPasswordReset } from "../../src/api/client";
import { AppCard, AppScreen, PrimaryButton } from "../../src/components";
import { colors, radius, spacing, typography } from "../../src/theme";

export default function ForgotPasswordScreen() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    await requestPasswordReset(email);
    setBusy(false);
    // Always the same outcome, even on a network failure. The endpoint
    // answers identically for a registered and an unregistered address so
    // that it cannot be used to find out who has an InfinityPay account,
    // and showing an error here would hand that difference back.
    setSent(true);
  }

  if (sent) {
    return (
      <AppScreen>
        <AppCard style={s.form}>
          <Text style={s.title}>Check your email</Text>
          <Text style={s.body}>
            If that address has an InfinityPay account, we’ve sent a reset link. Opening it takes you to
            the InfinityPay website to set a new password — then come back here and sign in.
          </Text>
          <Text style={s.body}>Check your spam folder if it has not arrived in a few minutes.</Text>
        </AppCard>
      </AppScreen>
    );
  }

  return (
    <AppScreen>
      <AppCard style={s.form}>
        <Text style={s.title}>Reset your password</Text>
        <Text style={s.body}>Enter the email you use to sign in and we’ll send you a reset link.</Text>

        <TextInput
          style={s.input}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          placeholder="you@business.co.tz"
          placeholderTextColor={colors.outline}
          inputMode="email"
        />

        <PrimaryButton
          label="Send reset link"
          onPress={() => void submit()}
          loading={busy}
          disabled={email.trim().length === 0}
        />
      </AppCard>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  form: { gap: spacing.md },
  title: { ...typography.title, color: colors.onSurface },
  body: { ...typography.body, color: colors.onSurfaceVariant },
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
});
