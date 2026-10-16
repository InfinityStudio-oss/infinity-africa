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
  const [enabled, setEnabled] = useState(true);
  const [smsEnabled, setSmsEnabled] = useState(false);
  const [smsPhone, setSmsPhone] = useState("");
  // The account contact number. Shown as the effective destination when
  // no SMS number has been entered, for the same reason the account
  // email is shown above: the toggle says alerts are on, so the page has
  // to say where they actually go.
  const [accountPhone, setAccountPhone] = useState<string | null>(null);
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
    getMyMerchant().then((merchant) => {
      setAccountEmail(merchant?.contact_email ?? null);
      setAccountPhone(merchant?.contact_phone ?? null);
    });
  }, []);

  function applySettings(settings: NotificationSettings | null) {
    setPrimary(settings?.primary_notification_email ?? "");
    setEnabled(settings?.collection_notifications_enabled ?? true);
    setSmsEnabled(settings?.collection_sms_enabled ?? false);
    setSmsPhone(settings?.sms_notification_phone ?? "");
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const updated = await updateMyNotificationSettings({
        primary_notification_email: primary.trim() || null,
        // Always cleared: the field is gone from the portal, and a
        // leftover address would keep receiving email the merchant can
        // no longer see or remove.
        secondary_notification_email: null,
        collection_notifications_enabled: enabled,
        collection_sms_enabled: smsEnabled,
        sms_notification_phone: smsPhone.trim(),
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
        {enabled && !primary.trim() && accountEmail && (
          <p className="rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
            No address set, so confirmations go to your account email,{" "}
            <span className="font-medium">{accountEmail}</span>. Add an address above to send them
            somewhere else.
          </p>
        )}

        <div className="border-t border-surface-container-highest pt-5">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={smsEnabled}
              onChange={(event) => setSmsEnabled(event.target.checked)}
            />
            <span className="text-sm text-on-surface">
              Also send me an SMS when a payment is confirmed.
            </span>
          </label>
          <p className="mt-1.5 ml-7 text-sm text-on-surface-variant">
            The message states the amount, our charge, what you received and your balance straight
            after that payment. It goes to you, never to the person who paid.
          </p>

          <div className="mt-4">
            <label className={labelClass}>SMS number</label>
            <input
              aria-label="SMS number"
              className={inputClass}
              type="tel"
              inputMode="tel"
              placeholder="e.g. 0712 345 678"
              value={smsPhone}
              onChange={(event) => setSmsPhone(event.target.value)}
            />
          </div>
          {smsEnabled && !smsPhone.trim() && accountPhone && (
            <p className="mt-3 rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
              No number set, so alerts go to your account number,{" "}
              <span className="font-medium">{accountPhone}</span>. Add a number above to send them
              somewhere else.
            </p>
          )}
          {smsEnabled && !smsPhone.trim() && !accountPhone && (
            <p className="mt-3 rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">
              There is no number on your account, so no SMS can be sent. Add one above.
            </p>
          )}
        </div>

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
