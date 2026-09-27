"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { getMyMerchant, getMyNotificationSettings, updateMyNotificationSettings } from "@/lib/portal/api";
import type { NotificationSettings } from "@/lib/portal/types";

const inputClass =
  "w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary";
const labelClass = "block text-sm font-medium text-on-surface-variant mb-1.5";

export function NotificationSettingsCard() {
  const [loading, setLoading] = useState(true);
  const [primary, setPrimary] = useState("");
  const [secondary, setSecondary] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; tone: "success" | "error" } | null>(null);
  // The account email. Shown as the effective recipient when no address
  // has been entered, because the backend falls back to it rather than
  // sending nothing — the toggle says notifications are on, so the page
  // has to say where they actually go.
  const [accountEmail, setAccountEmail] = useState<string | null>(null);

  useEffect(() => {
    getMyNotificationSettings().then((settings) => {
      applySettings(settings);
      setLoading(false);
    });
    getMyMerchant().then((merchant) => setAccountEmail(merchant?.contact_email ?? null));
  }, []);

  function applySettings(settings: NotificationSettings | null) {
    setPrimary(settings?.primary_notification_email ?? "");
    setSecondary(settings?.secondary_notification_email ?? "");
    setEnabled(settings?.collection_notifications_enabled ?? true);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const updated = await updateMyNotificationSettings({
        primary_notification_email: primary.trim() || null,
        secondary_notification_email: secondary.trim() || null,
        collection_notifications_enabled: enabled,
      });
      applySettings(updated);
      setMessage({ text: "Notification settings saved.", tone: "success" });
    } catch (err) {
      setMessage({
        text: err instanceof Error ? err.message : "Couldn't save notification settings. Try again.",
        tone: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <Card id="notifications" className="scroll-mt-24">
        <h3 className="text-2xl font-semibold text-on-background mb-2">Notification Settings</h3>
        <p className="text-sm text-on-surface-variant">Loading…</p>
      </Card>
    );
  }

  return (
    <Card id="notifications" className="scroll-mt-24">
      <h3 className="text-2xl font-semibold text-on-background mb-1">Notification Settings</h3>
      <p className="text-sm text-on-surface-variant mb-5">
        We will send confirmation emails to these addresses when collection payments are successfully confirmed.
      </p>

      {message && (
        <div
          className={
            message.tone === "success"
              ? "mb-5 rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface"
              : "mb-5 rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error"
          }
        >
          {message.text}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          <span className="text-sm text-on-surface">Receive collection transaction notifications by email.</span>
        </label>

        <div>
          <label className={labelClass}>Primary notification email</label>
          <input
            className={inputClass}
            type="email"
            placeholder="e.g. owner@yourbusiness.com"
            value={primary}
            onChange={(event) => setPrimary(event.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Secondary notification email (optional)</label>
          <input
            className={inputClass}
            type="email"
            placeholder="e.g. finance@yourbusiness.com"
            value={secondary}
            onChange={(event) => setSecondary(event.target.value)}
          />
          <p className="mt-1.5 text-xs text-on-surface-variant">You can add up to 2 notification emails.</p>
        </div>

        {enabled && !primary.trim() && !secondary.trim() && accountEmail && (
          <p className="rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
            No address set, so confirmations go to your account email,{" "}
            <span className="font-medium">{accountEmail}</span>. Add an address above to send them
            somewhere else.
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className="bg-primary-container text-on-primary text-sm font-medium py-3 px-6 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </form>
    </Card>
  );
}
