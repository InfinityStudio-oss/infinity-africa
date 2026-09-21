"use client";

import { useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { createIpAllowlistEntry, deleteIpAllowlistEntry, listIpAllowlist } from "@/lib/portal/api";
import type { IpAllowlistEntry } from "@/lib/portal/types";

const STATUS_TONE: Record<IpAllowlistEntry["status"], { label: string; tone: "positive" | "neutral" | "negative" }> = {
  active: { label: "Active", tone: "positive" },
  pending: { label: "Pending Approval", tone: "neutral" },
  rejected: { label: "Rejected", tone: "negative" },
};

export function IpAllowlistView() {
  const [entries, setEntries] = useState<IpAllowlistEntry[]>([]);
  const [environment, setEnvironment] = useState<IpAllowlistEntry["environment"]>("live");
  const [label, setLabel] = useState("");
  const [ip, setIp] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listIpAllowlist().then(setEntries);
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const entry = await createIpAllowlistEntry({
        environment,
        label,
        ip_address_or_cidr: ip,
        notes: notes || null,
      });
      setEntries((prev) => [entry, ...prev]);
      setLabel("");
      setIp("");
      setNotes("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add this IP address.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    await deleteIpAllowlistEntry(id);
    setEntries((prev) => prev.filter((entry) => entry.id !== id));
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="IP Allowlist"
        description="Restrict which server IPs can use your production API keys. Sandbox traffic is never restricted."
      />

      <Card>
        <form onSubmit={handleSubmit} className="space-y-5">
          <h3 className="text-2xl font-semibold text-on-background">Add a Server IP</h3>
          <p className="text-sm text-on-surface-variant -mt-3">
            Add your own server&rsquo;s IP address or CIDR block — InfinityPay never generates these for you. A new
            entry starts <span className="font-medium">Pending Approval</span> until reviewed.
          </p>

          <div className="grid sm:grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Environment</label>
              <select
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
                value={environment}
                onChange={(event) => setEnvironment(event.target.value as IpAllowlistEntry["environment"])}
              >
                <option value="live">Production (live)</option>
                <option value="sandbox">Sandbox</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Label</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
                placeholder="e.g. Main ecommerce server"
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                required
              />
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-5">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">IP Address or CIDR</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm font-mono"
                placeholder="41.222.10.5 or 41.222.10.0/24"
                value={ip}
                onChange={(event) => setIp(event.target.value)}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Notes (optional)</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
                placeholder="e.g. AWS EC2 instance, ap-south-1"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </div>
          </div>

          {error && <p className="text-sm text-error">{error}</p>}

          <button
            type="submit"
            disabled={saving || !label.trim() || !ip.trim()}
            className="bg-primary-container text-on-primary text-sm font-medium py-2.5 px-5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
          >
            {saving ? "Adding…" : "Add IP Address"}
          </button>
        </form>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Configured IPs</h3>
        </div>
        {entries.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">
            No IP addresses configured — your production API keys work from any IP until you add at least one
            active entry above.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[760px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Label</th>
                  <th className={thClass}>IP / CIDR</th>
                  <th className={thClass}>Environment</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Added</th>
                  <th className={`${thClass} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {entries.map((entry) => (
                  <tr key={entry.id} className="border-t border-surface-container-highest">
                    <td className={`${tdClass} font-medium text-on-background`}>{entry.label}</td>
                    <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>{entry.ip_address_or_cidr}</td>
                    <td className={`${tdClass} capitalize text-on-surface-variant`}>{entry.environment}</td>
                    <td className={tdClass}>
                      <StatusBadge {...STATUS_TONE[entry.status]} />
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(entry.created_at)}</td>
                    <td className={`${tdClass} text-right`}>
                      <button
                        type="button"
                        onClick={() => handleDelete(entry.id)}
                        className="p-1.5 text-on-surface-variant hover:text-error"
                        title="Remove"
                      >
                        <Icon name="delete" className="text-[18px]" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
