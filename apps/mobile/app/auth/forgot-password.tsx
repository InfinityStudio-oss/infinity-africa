/** Password reset request.
 *
 * Supabase emails the link; the link opens the web portal, which is
 * where the new password is set. One reset flow, one place it can go
 * wrong.
 */

import { useState } from "react";
import { StyleSheet, Text, TextInput } from "react-native";

import { sendPasswordReset } from "../../src/auth/session";
import { AppCard, AppScreen, PrimaryButton } from "../../src/components";
import { colors, radius, spacing, typography } from "../../src/theme";

export default function ForgotPasswordScreen() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    const { error: resetError } = await sendPasswordReset(email);
    setBusy(false);
    if (resetError) {
      setError(resetError);
      return;
    }
    // Shown whether or not the address exists — confirming which emails
    // have accounts would hand an attacker a merchant list.
    setSent(true);
  }

  if (sent) {
    return (
      <AppScreen>
        <AppCard style={s.form}>
          <Text style={s.title}>Check your email</Text>
          <Text style={s.body}>
            If that address has an InfinityPay account, we’ve sent a reset link. Open it to set a new
            password, then come back and sign in.
          </Text>
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

        {error ? <Text style={s.error}>{error}</Text> : null}

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
  error: { ...typography.body, color: colors.error },
});
