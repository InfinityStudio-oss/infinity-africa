/** IP Allowlist — which addresses may use this merchant's API keys.
 *
 * Read-only here. Adding an address is a security change, and one made
 * by mistake on a phone locks out a live integration; it belongs in the
 * portal where the consequence is spelled out.
 */

import { StyleSheet, Text } from "react-native";

import { IpAllowlistEntry, api } from "../../src/api/client";
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

export default function IpAllowlistScreen() {
  const { data, error, loading, refreshing, refresh, reload } = useApi(() => api.ipAllowlist());

  if (loading) return <AppScreen><LoadingState /></AppScreen>;
  if (error) return <AppScreen><ErrorState message={error} onRetry={reload} /></AppScreen>;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      {data && data.length > 0 ? (
        <AppCard>
          {data.map((entry: IpAllowlistEntry) => (
            <ListRow
              key={entry.id}
              title={entry.ip_address_or_cidr}
              meta={`${entry.label} · ${humanise(entry.environment)} · added ${formatDate(
                entry.created_at,
              )}`}
              right={<StatusBadge status={entry.status} />}
            />
          ))}
        </AppCard>
      ) : (
        <EmptyState
          title="No IP restrictions"
          message="Your API keys work from any address. Add an allowlist in the web portal to restrict them to your servers."
        />
      )}

      <Text style={s.note}>
        Allowlists are enforced by InfinityPay on every API call, not by this app.
      </Text>
    </AppScreen>
  );
}

const s = StyleSheet.create({
  note: { ...typography.caption, color: colors.onSurfaceVariant, textAlign: "center", marginTop: spacing.sm },
});
