"use client";

import { useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { EmptyState } from "@/components/portal/empty-state";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { getWebhookConfig, listWebhookEvents, sendTestWebhook, updateWebhookConfig } from "@/lib/portal/api";
import { webhookDeliveryBadge } from "@/lib/portal/status-tones";
import { WEBHOOK_EVENT_NAMES, type WebhookConfig, type WebhookEvent, type WebhookTestResult } from "@/lib/portal/types";

export function WebhooksView() {
  const [config, setConfig] = useState<WebhookConfig | null>(null);
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [allEvents, setAllEvents] = useState(true);
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<WebhookTestResult | null>(null);

  useEffect(() => {
    getWebhookConfig().then((data) => {
      if (!data) return;
      setConfig(data);
      setWebhookUrl(data.webhook_url ?? "");
      setAllEvents(!data.subscribed_events || data.subscribed_events.length === 0);
      setSelectedEvents(data.subscribed_events ?? []);
    });
    listWebhookEvents().then(setEvents);
  }, []);

  function toggleEvent(eventName: string) {
    setSelectedEvents((prev) =>
      prev.includes(eventName) ? prev.filter((e) => e !== eventName) : [...prev, eventName],
    );
  }

  async function handleSave(formEvent: React.FormEvent) {
    formEvent.preventDefault();
    setSaving(true);
    try {
      const updated = await updateWebhookConfig({
        webhook_url: webhookUrl,
        subscribed_events: allEvents ? [] : selectedEvents,
      });
      setConfig(updated);
    } finally {
      setSaving(false);
    }
  }

  async function handleRegenerateSecret() {
    setRegenerating(true);
    try {
      const updated = await updateWebhookConfig({ regenerate_secret: true });
      setConfig(updated);
      setRevealedSecret(updated.secret);
    } finally {
      setRegenerating(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await sendTestWebhook();
      setTestResult(result);
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader title="Webhooks" description="Configure where InfinityPay sends event notifications, and review delivery status." />

      <Card>
        <form onSubmit={handleSave} className="space-y-5">
          <h3 className="text-2xl font-semibold text-on-background">Webhook Configuration</h3>

          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Webhook URL</label>
            <input
              className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm font-mono"
              placeholder="https://your-app.example.com/webhooks/infinity"
              type="url"
              value={webhookUrl}
              onChange={(event) => setWebhookUrl(event.target.value)}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-2">Events to Subscribe To</label>
            <label className="flex items-center gap-2.5 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg cursor-pointer mb-2.5 w-fit">
              <input
                checked={allEvents}
                onChange={(event) => setAllEvents(event.target.checked)}
                className="rounded border-outline-variant text-primary-container focus:ring-primary"
                type="checkbox"
              />
              <span className="text-sm font-medium text-on-surface">All events</span>
            </label>
            {!allEvents && (
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                {WEBHOOK_EVENT_NAMES.map((eventName) => (
                  <label
                    key={eventName}
                    className="flex items-center gap-2.5 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg cursor-pointer"
                  >
                    <input
                      checked={selectedEvents.includes(eventName)}
                      onChange={() => toggleEvent(eventName)}
                      className="rounded border-outline-variant text-primary-container focus:ring-primary"
                      type="checkbox"
                    />
                    <span className="text-xs font-mono text-on-surface">{eventName}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving || !webhookUrl.trim()}
              className="bg-primary-container text-on-primary text-sm font-medium py-2.5 px-5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save Configuration"}
            </button>
            <button
              type="button"
              onClick={handleRegenerateSecret}
              disabled={regenerating}
              className="text-sm font-medium text-on-surface-variant hover:text-on-background disabled:opacity-60"
            >
              {regenerating ? "Generating…" : config?.has_secret ? "Regenerate Secret" : "Generate Secret"}
            </button>
            <button
              type="button"
              onClick={handleTest}
              disabled={testing || !config?.webhook_url}
              className="text-sm font-medium text-primary hover:underline disabled:opacity-60 disabled:no-underline"
            >
              {testing ? "Sending…" : "Send Test Webhook"}
            </button>
          </div>

          {revealedSecret && (
            <div className="border border-primary rounded-lg p-4">
              <p className="text-sm text-error font-medium mb-2">
                Copy this secret now. You will not be able to view it again.
              </p>
              <code className="block bg-on-surface text-primary-fixed text-sm px-4 py-3 rounded-lg font-mono break-all">
                {revealedSecret}
              </code>
            </div>
          )}

          {testResult && (
            <div
              className={`flex items-center gap-2.5 text-sm px-3.5 py-2.5 rounded-lg ${testResult.delivered ? "bg-primary-container/10 text-primary" : "bg-error-container/10 text-error"}`}
            >
              <Icon name={testResult.delivered ? "check_circle" : "error"} className="text-[18px]" />
              {testResult.delivered
                ? `Delivered — HTTP ${testResult.http_status} in ${testResult.latency_ms}ms`
                : `Delivery failed${testResult.http_status ? ` — HTTP ${testResult.http_status}` : " — endpoint unreachable"}`}
            </div>
          )}

          {config?.last_delivery && (
            <p className="text-xs text-on-surface-variant">
              Last delivery: <span className="font-mono">{config.last_delivery.event_name}</span> —{" "}
              {config.last_delivery.status} ({formatDateTime(config.last_delivery.created_at)})
            </p>
          )}
        </form>
      </Card>

      {events.length === 0 ? (
        <Card>
          <EmptyState
            icon="webhook"
            heading="No webhook deliveries yet"
            body="Once you configure a webhook URL above, events like payment_link.paid and invoice.paid will queue here."
            actionLabel="Send Test Webhook"
            onAction={handleTest}
          />
        </Card>
      ) : (
        <Card padded={false}>
          <div className="p-5 pb-3">
            <h3 className="text-2xl font-semibold text-on-background">Delivery Log</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[760px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Event</th>
                  <th className={thClass}>Target URL</th>
                  <th className={thClass}>Timestamp</th>
                  <th className={thClass}>HTTP Status</th>
                  <th className={thClass}>Status</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {events.map((event) => (
                  <tr key={event.id} className="border-t border-surface-container-highest">
                    <td className={`${tdClass} font-mono text-xs`}>{event.event_name}</td>
                    <td className={tdClass}>
                      <span className="font-mono text-xs text-on-surface-variant truncate block max-w-[240px]">{event.target_url}</span>
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(event.created_at)}</td>
                    <td className={`${tdClass} font-mono text-sm ${event.response_status_code && event.response_status_code < 400 ? "text-primary" : "text-error"}`}>
                      {event.response_status_code ?? "—"}
                    </td>
                    <td className={tdClass}>
                      <StatusBadge {...webhookDeliveryBadge(event.status)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
