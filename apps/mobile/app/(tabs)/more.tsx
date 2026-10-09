/** More — everything that isn't a daily balance check.
 *
 * The list mirrors the merchant portal's own sections, so a merchant
 * who learns one learns the other. Super Admin sections are not here
 * and not reachable: there is no admin surface in this app at all.
 */

import { useRouter } from "expo-router";
import { Alert, StyleSheet, Text } from "react-native";

import { api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import {
  AppCard,
  AppScreen,
  ListRow,
  PrimaryButton,
  SectionHeader,
  StatusBadge,
} from "../../src/components";
import { signOut } from "../../src/auth/session";
import { colors, maskPhone, spacing, typography } from "../../src/theme";

const LINKS = [
  { title: "API Credentials", meta: "Publishable and secret keys", href: "/more/api-credentials" },
  { title: "Webhooks", meta: "Endpoint and recent deliveries", href: "/more/webhooks" },
  { title: "IP Allowlist", meta: "Addresses allowed to use your keys", href: "/more/ip-allowlist" },
  { title: "Reports", meta: "Settlement and collection summaries", href: "/more/reports" },
  { title: "Support", meta: "Get help from the InfinityPay team", href: "/more/support" },
  { title: "Settings", meta: "Notifications and account details", href: "/more/settings" },
] as const;

export default function MoreScreen() {
  const router = useRouter();
  const { data, refreshing, refresh } = useApi(() => api.me());

  function confirmSignOut() {
    Alert.alert("Sign out?", "You'll need your email and password to sign back in.", [
      { text: "Cancel", style: "cancel" },
      { text: "Sign out", style: "destructive", onPress: () => void signOut() },
    ]);
  }

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      {data ? (
        <AppCard style={s.identity}>
          <Text style={s.business}>{data.business_name}</Text>
          <Text style={s.meta}>{data.merchant_code ? `ID ${data.merchant_code}` : "—"}</Text>
          <Text style={s.meta}>{maskPhone(data.contact_phone)}</Text>
          <StatusBadge status={data.status} />
        </AppCard>
      ) : null}

      <SectionHeader title="Manage" />
      <AppCard>
        {LINKS.map((link) => (
          <ListRow
            key={link.href}
            title={link.title}
            meta={link.meta}
            onPress={() => router.push(link.href)}
          />
        ))}
      </AppCard>

      <PrimaryButton label="Sign out" variant="outline" onPress={confirmSignOut} />

      <Text style={s.note}>
        Platform administration — merchant approvals, pricing and risk — is only available in the web portal.
      </Text>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  identity: { gap: spacing.xs, alignItems: "flex-start" },
  business: { ...typography.title, color: colors.onSurface },
  meta: { ...typography.caption, color: colors.onSurfaceVariant },
  note: { ...typography.caption, color: colors.onSurfaceVariant, textAlign: "center" },
});
