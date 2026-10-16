"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { formatDateTime } from "@/lib/format";
import {
  updateAdminMerchantNotificationSettingsAction,
  type NotificationSettingsActionState,
} from "@/lib/admin/live-actions";
import type { AdminNotificationSettingsRow } from "@/lib/admin/types";

const inputClass =
  "w-full px-3 py-2 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1.5";

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="bg-primary-container text-on-primary text-sm font-medium px-5 py-2 rounded-lg hover:opacity-90 disabled:opacity-60"
    >
      {pending ? "Saving…" : "Save"}
    </button>
  );
}

function statusTone(status: string | null): string {
  if (status === "sent") return "text-primary";
  if (status === "failed") return "text-error";
  if (status === "skipped") return "text-on-surface-variant";
  return "text-on-surface-variant";
}

export function NotificationSettingsCard({
  merchantId,
  settings,
}: {
  merchantId: string;
  settings: AdminNotificationSettingsRow;
}) {
  const [editing, setEditing] = useState(false);
  const [state, formAction] = useActionState<NotificationSettingsActionState, FormData>(
    updateAdminMerchantNotificationSettingsAction.bind(null, merchantId),
    { error: null },
  );

  return (
    <Card padded={false}>
      <div className="p-5 pb-3 flex items-center justify-between">
        <h3 className="text-xl font-semibold text-on-background">Notification Details</h3>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="text-xs font-semibold text-primary hover:underline"
        >
          {editing ? "Cancel" : "Edit"}
        </button>
      </div>

      {editing ? (
        <form action={formAction} className="px-5 pb-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className={labelClass}>Primary notification email</label>
              <input
                name="primary_notification_email"
                type="email"
                defaultValue={settings.primary_notification_email ?? ""}
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass}>Secondary notification email</label>
              <input
                name="secondary_notification_email"
                type="email"
                defaultValue={settings.secondary_notification_email ?? ""}
                className={inputClass}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-on-surface">
            <input
              type="checkbox"
              name="collection_notifications_enabled"
              defaultChecked={settings.collection_notifications_enabled}
            />
            Collection notifications enabled
          </label>

          {/* How SMS is turned on merchant by merchant during rollout.
              Off by default for every merchant — enabling it for all 60
              at once is a cost and a consent decision. */}
          <label className="flex items-center gap-2 text-sm text-on-surface">
            <input
              type="checkbox"
              name="collection_sms_enabled"
              defaultChecked={settings.collection_sms_enabled ?? false}
            />
            Payment alerts by SMS
          </label>
          <div>
            <label className={labelClass}>SMS number</label>
            <input
              name="sms_notification_phone"
              type="tel"
              defaultValue={settings.sms_notification_phone ?? ""}
              placeholder="Blank uses the account contact number"
              className={inputClass}
            />
            <p className="mt-1 text-xs text-on-surface-variant">
              The merchant&apos;s own number. Changing it redirects their payment alerts, so it is
              recorded in the audit log.
            </p>
          </div>
          {state.error && <div className="rounded-lg bg-error/10 px-4 py-3 text-sm text-error">{state.error}</div>}
          <SubmitButton />
        </form>
      ) : (
        <div className="px-5 pb-5 space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">Primary email</span>
            <span className="text-on-background">{settings.primary_notification_email ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">Secondary email</span>
            <span className="text-on-background">{settings.secondary_notification_email ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">Status</span>
            <span className={settings.collection_notifications_enabled ? "text-primary font-medium" : "text-on-surface-variant"}>
              {settings.collection_notifications_enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">SMS alerts</span>
            <span className={settings.collection_sms_enabled ? "text-primary font-medium" : "text-on-surface-variant"}>
              {settings.collection_sms_enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">SMS number</span>
            <span className="text-on-background">
              {settings.sms_notification_phone ?? "Account contact number"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">Last notification</span>
            <span className={`text-xs ${statusTone(settings.last_notification_status)}`}>
              {settings.last_notification_status && settings.last_notification_sent_at
                ? `${settings.last_notification_status} · ${formatDateTime(settings.last_notification_sent_at)}`
                : "Never sent"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">Failed deliveries</span>
            <span className={settings.failed_notification_count > 0 ? "text-error font-medium" : "text-on-background"}>
              {settings.failed_notification_count}
            </span>
          </div>
        </div>
      )}

      {settings.recent_deliveries.length > 0 && (
        <div className="border-t border-surface-container-highest overflow-x-auto">
          <table className="w-full text-left min-w-[500px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold">
                <th className={thClass}>Recipient</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>Sent</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {settings.recent_deliveries.slice(0, 10).map((delivery) => (
                <tr key={delivery.id} className="border-t border-surface-container-highest">
                  <td className={`${tdClass} text-xs`}>{delivery.recipient_email}</td>
                  <td className={`${tdClass} ${statusTone(delivery.status)}`}>{delivery.status}</td>
                  <td className={`${tdClass} text-xs text-on-surface-variant`}>{formatDateTime(delivery.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
