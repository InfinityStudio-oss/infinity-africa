"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { ToggleSwitch } from "@/components/portal/toggle-switch";
import { listAdminTeam } from "@/lib/admin/api";
import type { AdminTeamMember } from "@/lib/admin/types";

const TABS = [
  { label: "Platform", href: "#platform" },
  { label: "Security", href: "#security" },
  { label: "Notifications", href: "#notifications" },
  { label: "Admin Team", href: "#admins" },
];

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

export default function AdminSettingsPage() {
  const [team, setTeam] = useState<AdminTeamMember[]>([]);
  const [security, setSecurity] = useState(() => Object.fromEntries(SECURITY_DEFAULTS.map((item) => [item.key, item.checked])));
  const [notifications, setNotifications] = useState(() => Object.fromEntries(NOTIFICATION_DEFAULTS.map((item) => [item.key, item.checked])));

  useEffect(() => {
    listAdminTeam().then(setTeam);
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader title="Settings" description="Platform-wide configuration and admin team management." />

      <div className="flex flex-wrap gap-2">
        {TABS.map((tab, index) => (
          <a
            key={tab.href}
            href={tab.href}
            className={
              index === 0
                ? "px-4 py-2 rounded-full bg-primary-container text-on-primary text-sm font-semibold"
                : "px-4 py-2 rounded-full bg-surface-container-low text-on-surface-variant text-sm font-semibold hover:bg-surface-container-highest transition-colors"
            }
          >
            {tab.label}
          </a>
        ))}
      </div>

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

      <Card id="admins" className="scroll-mt-24">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-2xl font-semibold text-on-background">Admin Team</h3>
          <button className="bg-primary-container text-on-primary text-sm font-medium py-2 px-4 rounded-lg hover:opacity-90 transition-opacity flex items-center gap-2">
            Invite Admin
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className="px-5 py-3 font-semibold">Admin</th>
                <th className="px-5 py-3 font-semibold">Role</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {team.map((member) => (
                <tr key={member.id} className="border-t border-surface-container-highest">
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-xs shrink-0">
                        {member.name.charAt(0)}
                      </div>
                      <div>
                        <div className="font-medium text-on-background">{member.name}</div>
                        <div className="text-xs text-on-surface-variant">{member.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3.5 text-on-surface-variant">{member.role}</td>
                  <td className="px-5 py-3.5">
                    <StatusBadge label="Active" tone="positive" dot />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
