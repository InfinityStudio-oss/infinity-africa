/** Root layout: decides whether a merchant sees the app or the login
 * screen, and nothing else.
 *
 * The gate is the Supabase session only. Whether a merchant may
 * actually collect, withdraw or create live keys is not decided here —
 * that is the API's job, and the screens show whatever it says. A
 * client-side check would be a convenience at best and a bypass at
 * worst.
 */

import { Stack, useRouter, useSegments } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { supabase } from "../src/auth/session";
import { colors } from "../src/theme";

export default function RootLayout() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSignedIn(Boolean(data.session)));
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setSignedIn(Boolean(session));
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (signedIn === null) return;
    const inAuth = segments[0] === "auth";
    if (!signedIn && !inAuth) router.replace("/auth/login");
    if (signedIn && inAuth) router.replace("/");
  }, [signedIn, segments, router]);

  if (signedIn === null) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background }}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <SafeAreaProvider>
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.primary },
          headerTintColor: colors.onPrimary,
          headerTitleStyle: { fontWeight: "700" },
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="auth/login" options={{ headerShown: false }} />
        <Stack.Screen name="auth/forgot-password" options={{ title: "Reset password" }} />
        <Stack.Screen name="more/api-credentials" options={{ title: "API Credentials" }} />
        <Stack.Screen name="more/webhooks" options={{ title: "Webhooks" }} />
        <Stack.Screen name="more/ip-allowlist" options={{ title: "IP Allowlist" }} />
        <Stack.Screen name="more/reports" options={{ title: "Reports" }} />
        <Stack.Screen name="more/support" options={{ title: "Support" }} />
        <Stack.Screen name="more/settings" options={{ title: "Settings" }} />
      </Stack>
    </SafeAreaProvider>
  );
}
