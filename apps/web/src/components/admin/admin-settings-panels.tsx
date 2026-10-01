"use client";

import { useState } from "react";

import { Card } from "@/components/portal/card";
import { ToggleSwitch } from "@/components/portal/toggle-switch";

/**
 * The Platform / Security / Notifications cards, lifted out of the page
 * unchanged when the Admin Team card became server-rendered.
 *
 * These controls are still a prototype: the form's submit handler calls
 * preventDefault() and nothing else, and both toggle groups hold local
 * React state that is discarded on navigation. Nothing here reaches the
 * backend, and none of it reflects a real setting — the live equivalents
 * are Railway environment variables. Kept as-is rather than quietly
 * deleted, but labelled so the next person does not mistake them for
 * working controls.
 */

const SECURITY_DEFAULTS = [
  { key: "require_2fa", title: "Require 2FA for all admins", description: "Enforce two-factor authentication platform-wide", checked: true },
  { key: "ip_allowlist", title: "IP allowlist for admin login", description: "Restrict admin dashboard access to approved IP ranges", checked: false },
  { key: "auto_lock", title: "Auto-lock idle sessions", description: "Sign out inactive admin sessions after 30 minutes", checked: true },
];

const NOTIFICATION_DEFAULTS = [
  { key: "high_value", title: "High-value payout alerts", description: "Notify admins when a payout exceeds TZS 1,000,000", checked: true },
  { key: "downtime", title: "Provider downtime alerts", description: "Notify admins immediately when a provider goes down", checked: true },
  { key: "daily_summary", title: "Daily platform summary email", description: "Send a daily digest of platform activity to all admins", checked: true },
];

export function AdminSettingsPanels() {
  const [security, setSecurity] = useState(() => Object.fromEntries(SECURITY_DEFAULTS.map((item) => [item.key, item.checked])));
  const [notifications, setNotifications] = useState(() => Object.fromEntries(NOTIFICATION_DEFAULTS.map((item) => [item.key, item.checked])));

  return (
    <>
      <Card id="platform" className="scroll-mt-24">
        <h3 className="text-2xl font-semibold text-on-background mb-5">Platform Configuration</h3>
        <form onSubmit={(event) => event.preventDefault()} className="grid sm:grid-cols-2 gap-5">
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Platform Name</label>
            <input className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" defaultValue="InfinityPay" type="text" />
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Support Email</label>
            <input className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" defaultValue="info@infinitypay.me" type="email" />
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Support Phone</label>
            <input className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" defaultValue="+255 747 730 270" type="tel" />
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Default Currency</label>
            <select className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm" defaultValue="TZS">
              <option>TZS</option>
              <option>USD</option>
            </select>
          </div>
          <button className="sm:col-span-2 sm:w-auto sm:ml-auto bg-primary-container text-on-primary text-sm font-medium py-3 px-6 rounded-lg hover:opacity-90 transition-opacity" type="submit">
            Save Changes
          </button>
        </form>
      </Card>

      <Card id="security" className="scroll-mt-24">
        <h3 className="text-2xl font-semibold text-on-background mb-5">Security</h3>
        <div className="divide-y divide-surface-container-highest">
          {SECURITY_DEFAULTS.map((item) => (
            <div key={item.key} className="flex items-center justify-between py-3.5 first:pt-0 last:pb-0">
              <div>
                <p className="font-semibold text-sm text-on-background">{item.title}</p>
                <p className="text-sm text-on-surface-variant">{item.description}</p>
              </div>
              <ToggleSwitch checked={security[item.key]} onChange={(checked) => setSecurity((prev) => ({ ...prev, [item.key]: checked }))} label={item.title} />
            </div>
          ))}
        </div>
      </Card>

      <Card id="notifications" className="scroll-mt-24">
        <h3 className="text-2xl font-semibold text-on-background mb-5">Notifications</h3>
        <div className="divide-y divide-surface-container-highest">
          {NOTIFICATION_DEFAULTS.map((item) => (
            <div key={item.key} className="flex items-center justify-between py-3.5 first:pt-0 last:pb-0">
              <div>
                <p className="font-semibold text-sm text-on-background">{item.title}</p>
                <p className="text-sm text-on-surface-variant">{item.description}</p>
              </div>
              <ToggleSwitch
                checked={notifications[item.key]}
                onChange={(checked) => setNotifications((prev) => ({ ...prev, [item.key]: checked }))}
                label={item.title}
              />
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
