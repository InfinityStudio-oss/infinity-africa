/** Merchant sign-in.
 *
 * The same credentials as the web portal, against the same Supabase
 * project. There is no mobile-only account, and no sign-up here on
 * purpose: onboarding collects business details and KYC documents and
 * ends in a Super Admin approval, which belongs on the web.
 */

import { Link, useRouter } from "expo-router";
import { useState } from "react";
import { KeyboardAvoidingView, Platform, StyleSheet, Text, TextInput, View } from "react-native";

import { isSupabaseConfigured, signIn } from "../../src/auth/session";
import { AppCard, AppScreen, PrimaryButton } from "../../src/components";
import { colors, radius, spacing, typography } from "../../src/theme";

export default function LoginScreen() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const configured = isSupabaseConfigured();

  async function submit() {
    setBusy(true);
    setError(null);
    const { error: signInError } = await signIn(email, password);
    setBusy(false);
    if (signInError) {
      setError(signInError);
      return;
    }
    // The root layout watches the session and will swap to the tabs; the
    // replace is just so the login screen cannot be swiped back to.
    router.replace("/");
  }

  return (
    <AppScreen>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={s.brand}>
          <Text style={s.wordmark}>InfinityPay</Text>
          <Text style={s.tagline}>Collect and settle, from your pocket.</Text>
        </View>

        {!configured ? (
          <AppCard style={s.warning}>
            <Text style={s.warningTitle}>App not configured</Text>
            <Text style={s.warningBody}>
              Set EXPO_PUBLIC_SUPABASE_URL, EXPO_PUBLIC_SUPABASE_ANON_KEY and EXPO_PUBLIC_API_BASE_URL in
              apps/mobile/.env before signing in. See .env.example.
            </Text>
          </AppCard>
        ) : null}

        <AppCard style={s.form}>
          <Text style={s.label}>Email</Text>
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

          <Text style={s.label}>Password</Text>
          <TextInput
            style={s.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
            autoComplete="current-password"
            placeholder="••••••••"
            placeholderTextColor={colors.outline}
            onSubmitEditing={() => void submit()}
          />

          {error ? <Text style={s.error}>{error}</Text> : null}

          <PrimaryButton
            label="Sign in"
            onPress={() => void submit()}
            loading={busy}
            disabled={!configured || email.trim().length === 0 || password.length === 0}
          />

          <Link href="/auth/forgot-password" style={s.link}>
            Forgot your password?
          </Link>
        </AppCard>

        <Text style={s.note}>
          New to InfinityPay? Businesses sign up at infinitypay.me, where we collect your details for
          verification.
        </Text>
      </KeyboardAvoidingView>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  brand: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.xxl },
  wordmark: { ...typography.display, color: colors.primary },
  tagline: { ...typography.body, color: colors.onSurfaceVariant },
  form: { gap: spacing.sm },
  label: { ...typography.label, color: colors.onSurfaceVariant, marginTop: spacing.sm },
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
  error: { ...typography.body, color: colors.error, marginTop: spacing.sm },
  link: { ...typography.label, color: colors.primary, textAlign: "center", paddingTop: spacing.md },
  note: { ...typography.caption, color: colors.onSurfaceVariant, textAlign: "center", marginTop: spacing.lg },
  warning: { backgroundColor: colors.warningContainer, borderColor: colors.warningContainer, gap: spacing.xs },
  warningTitle: { ...typography.heading, color: colors.warning },
  warningBody: { ...typography.body, color: colors.warning },
});
