"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { getMyMerchant, getMyNotificationSettings } from "@/lib/portal/api";
import type { NotificationSettings } from "@/lib/portal/types";

/**
 * Read-only from 2026-11-01.
 *
 * This used to be a form: a checkbox, an address field and a Save
 * button. Collection notification settings became an InfinityPay control
 * on that date — who is told about a merchant's money, and at which
 * address, is a support decision. A merchant who switched their own
 * notifications off and forgot would later report that payments had
 * stopped arriving.
 *
 * It still SHOWS the state, because hiding it would be worse: a business
 * that cannot see whether notifications are on has no way to know what
 * to ask support for. What it no longer does is pretend the merchant can
 * change it — the backend refuses the write with a 403, and a form whose
 * Save button always failed would be a worse answer than no form.
 *
 * The toggle for SMS was never here; that has been a Super Admin control
 * since 2026-10-17.
 */
export function NotificationSettingsCard() {
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [accountEmail, setAccountEmail] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getMyNotificationSettings(), getMyMerchant()])
      .then(([loaded, merchant]) => {
        if (cancelled) return;
        // A null here is a failed read, not "switched off" — saying
        // "Disabled" because a request failed would send a merchant to
        // support about a setting that is fine.
        if (loaded === null) setFailed(true);
        setSettings(loaded);
        setAccountEmail(merchant?.contact_email ?? null);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const enabled = settings?.collection_notifications_enabled ?? null;
  const configured = settings?.primary_notification_email ?? null;
  // What an email actually goes to: the configured address, or the
  // account's own if none was set. Matches the backend's fallback.
  const recipient = configured || accountEmail;

  return (
    <Card>
      <h3 className="text-lg font-semibold text-on-surface mb-1">Payment notification emails</h3>
      <p className="text-sm text-on-surface-variant mb-4">
        Where we email you when one of your collections succeeds.
      </p>

      {loading ? (
        <p className="text-sm text-on-surface-variant">Loading…</p>
      ) : failed ? (
        <p className="text-sm text-on-surface-variant">
          Couldn&apos;t load your notification settings just now. This doesn&apos;t affect whether
          emails are sent — try again in a moment.
        </p>
      ) : (
        <dl className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <dt className="text-on-surface-variant">Status</dt>
            <dd className="font-semibold text-on-background">
              {enabled ? "On" : "Off"}
            </dd>
          </div>
          {enabled && (
            <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
              <dt className="text-on-surface-variant">Sent to</dt>
              <dd className="font-medium text-on-background break-all">
                {recipient ?? "—"}
                {!configured && recipient && (
                  <span className="block text-xs text-on-surface-variant font-normal mt-0.5">
                    Your account email, because no separate notification address is set.
                  </span>
                )}
              </dd>
            </div>
          )}
        </dl>
      )}

      <p className="text-xs text-on-surface-variant mt-5 pt-4 border-t border-surface-container-highest">
        Collection email notifications are managed by InfinityPay. Contact support to request a
        change.
      </p>
    </Card>
  );
}
