/** Webhooks — where events are sent, and whether they arrived.
 *
 * The signing secret is never fetched or shown; the API reports only
 * whether one is configured. Changing the endpoint or rotating the
 * secret happens in the web portal.
 */

import { StyleSheet, Text } from "react-native";

import { WebhookEvent, api } from "../../src/api/client";
import { useApi } from "../../src/api/useApi";
import {
  AppCard,
  AppScreen,
  EmptyState,
  ErrorState,
  ListRow,
  LoadingState,
  SectionHeader,
  StatusBadge,
  formatDate,
  humanise,
} from "../../src/components";
import { colors, spacing, typography } from "../../src/theme";

export default function WebhooksScreen() {
  const config = useApi(() => api.webhookConfig());
  const events = useApi(() => api.webhookEvents({ pageSize: 25 }));

  const refresh = () => {
    void config.refresh();
    void events.refresh();
  };

  if (config.loading) return <AppScreen><LoadingState /></AppScreen>;
  if (config.error)
    return <AppScreen><ErrorState message={config.error} onRetry={config.reload} /></AppScreen>;

  return (
    <AppScreen refreshing={config.refreshing || events.refreshing} onRefresh={refresh}>
      <AppCard style={s.configCard}>
        <Text style={s.label}>ENDPOINT</Text>
        <Text style={s.url} numberOfLines={2}>
          {config.data?.webhook_url ?? "Not configured"}
        </Text>
        <Text style={s.note}>
          {config.data?.has_secret
            ? "A signing secret is set. Verify every delivery against it."
            : "No signing secret set. Add one in the web portal so you can prove an event came from us."}
        </Text>

        <Text style={s.label}>SUBSCRIBED EVENTS</Text>
        <Text style={s.note}>
          {config.data?.subscribed_events?.length
            ? config.data.subscribed_events.join(", ")
            : "All events"}
        </Text>
      </AppCard>

      <SectionHeader title="Recent deliveries" />
      {events.loading ? <LoadingState /> : null}
      {events.error ? <ErrorState message={events.error} onRetry={events.reload} /> : null}

      {!events.loading && !events.error ? (
        events.data && events.data.length > 0 ? (
          <AppCard>
            {events.data.map((event: WebhookEvent) => (
              <ListRow
                key={event.id}
                title={humanise(event.event_name)}
                meta={`${formatDate(event.created_at)} · ${event.attempts} attempt${
                  event.attempts === 1 ? "" : "s"
                }`}
                right={<StatusBadge status={event.status} />}
                rightMeta={event.response_status_code ? `HTTP ${event.response_status_code}` : undefined}
              />
            ))}
          </AppCard>
        ) : (
          <EmptyState
            title="No deliveries yet"
            message="Once your endpoint is set, every event we send you will be listed here with its result."
          />
        )
      ) : null}
    </AppScreen>
  );
}

const s = StyleSheet.create({
  configCard: { gap: spacing.xs },
  label: { ...typography.caption, color: colors.onSurfaceVariant, letterSpacing: 0.5 },
  url: { ...typography.heading, color: colors.onSurface },
  note: { ...typography.body, color: colors.onSurfaceVariant, marginTop: spacing.xs },
});
