/** API Credentials — what keys exist, not what they say.
 *
 * This screen shows prefixes, environments and last-used dates. It never
 * shows a secret key and never stores one: the API only returns a secret
 * once, at creation, and creation stays in the web portal. A secret
 * sitting in a phone's storage is a secret waiting to leak.
 */

import { StyleSheet, Text } from "react-native";

import { ApiKey, api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import {
  AppCard,
  AppScreen,
  EmptyState,
  ErrorState,
  ListRow,
  LoadingState,
  StatusBadge,
  formatDate,
  humanise,
} from "../../src/components";
import { colors, spacing, typography } from "../../src/theme";

export default function ApiCredentialsScreen() {
  const { data, error, loading, refreshing, refresh, reload } = useApi(() => api.apiKeys());

  if (loading) return <AppScreen><LoadingState /></AppScreen>;
  if (error) return <AppScreen><ErrorState message={error} onRetry={reload} /></AppScreen>;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      {data && data.length > 0 ? (
        <AppCard>
          {data.map((key: ApiKey) => (
            <ListRow
              key={key.id}
              title={key.name}
              meta={`${humanise(key.environment)} · ${key.key_prefix}…${key.key_last4 ?? ""}`}
              right={<StatusBadge status={key.status} />}
              rightMeta={key.last_used_at ? `Used ${formatDate(key.last_used_at)}` : "Never used"}
            />
          ))}
        </AppCard>
      ) : (
        <EmptyState
          title="No API keys"
          message="Create keys in the web portal under API Credentials. They'll be listed here afterwards."
        />
      )}

      <AppCard style={s.notice}>
        <Text style={s.noticeTitle}>Secret keys are never shown here</Text>
        <Text style={s.noticeBody}>
          A secret key is displayed once, when you create it in the web portal. If you’ve lost one, revoke it
          and issue a new key — it cannot be read back on any device.
        </Text>
      </AppCard>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  notice: { backgroundColor: colors.surfaceLow, gap: spacing.xs },
  noticeTitle: { ...typography.heading, color: colors.onSurface },
  noticeBody: { ...typography.body, color: colors.onSurfaceVariant },
});
