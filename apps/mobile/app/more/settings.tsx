/** Settings — what this account is, and where its alerts go.
 *
 * Read-only. Changing a notification address or a business detail is a
 * change a Super Admin may need to see, and it has one home: the web
 * portal. Showing the values here saves a merchant a login; letting
 * them be edited in two places would not.
 */

import { Alert, StyleSheet, Text, View } from "react-native";

import { API_BASE, api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import {
  AppCard,
  AppScreen,
  ErrorState,
  LoadingState,
  PrimaryButton,
  SectionHeader,
  StatusBadge,
  humanise,
} from "../../src/components";
import { signOut } from "../../src/auth/session";
import { colors, maskPhone, spacing, typography } from "../../src/theme";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.field}>
      <Text style={s.fieldLabel}>{label}</Text>
      <Text style={s.fieldValue}>{value}</Text>
    </View>
  );
}

export default function SettingsScreen() {
  const merchant = useApi(() => api.me());
  const notifications = useApi(() => api.notificationSettings());

  const refresh = () => {
    void merchant.refresh();
    void notifications.refresh();
  };

  function confirmSignOut() {
    Alert.alert("Sign out?", "You'll need your email and password to sign back in.", [
      { text: "Cancel", style: "cancel" },
      { text: "Sign out", style: "destructive", onPress: () => void signOut() },
    ]);
  }

  if (merchant.loading) return <AppScreen><LoadingState /></AppScreen>;
  if (merchant.error)
    return <AppScreen><ErrorState message={merchant.error} onRetry={merchant.reload} /></AppScreen>;

  return (
    <AppScreen refreshing={merchant.refreshing || notifications.refreshing} onRefresh={refresh}>
      <SectionHeader title="Business" />
      <AppCard style={s.card}>
        <Field label="Business name" value={merchant.data?.business_name ?? "—"} />
        <Field label="Merchant ID" value={merchant.data?.merchant_code ?? "—"} />
        <Field label="Contact phone" value={maskPhone(merchant.data?.contact_phone)} />
        <View style={s.field}>
          <Text style={s.fieldLabel}>Account status</Text>
          <StatusBadge status={merchant.data?.status ?? "unknown"} />
        </View>
        {merchant.data?.kyc_status ? (
          <Field label="Verification" value={humanise(merchant.data.kyc_status)} />
        ) : null}
      </AppCard>

      <SectionHeader title="Notifications" />
      <AppCard style={s.card}>
        <Field
          label="Primary email"
          value={notifications.data?.primary_notification_email ?? "—"}
        />
        <Field
          label="Secondary email"
          value={notifications.data?.secondary_notification_email ?? "—"}
        />
        <Field
          label="Collection emails"
          value={notifications.data?.collection_notifications_enabled ? "On" : "Off"}
        />
        <Text style={s.note}>Change these in the web portal under Settings.</Text>
      </AppCard>

      <SectionHeader title="App" />
      <AppCard style={s.card}>
        {/* Useful when a merchant is unsure which environment they are
            looking at. It is a hostname, not a credential. */}
        <Field label="Connected to" value={API_BASE} />
      </AppCard>

      <PrimaryButton label="Sign out" variant="outline" onPress={confirmSignOut} />
    </AppScreen>
  );
}

const s = StyleSheet.create({
  card: { gap: spacing.md },
  field: { gap: 2 },
  fieldLabel: { ...typography.caption, color: colors.onSurfaceVariant },
  fieldValue: { ...typography.label, color: colors.onSurface },
  note: { ...typography.caption, color: colors.onSurfaceVariant },
});
