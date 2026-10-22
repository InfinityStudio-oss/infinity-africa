import { Card } from "@/components/portal/card";
import type { EffectiveSettingsReport } from "@/lib/admin/types";

/**
 * What the running API actually believes, not what the dashboard was told.
 *
 * A variable that is absent, misspelled or unreadable all produce the same
 * outcome - the field's default - and two of those three are completely
 * silent. On 2026-10-22 that cost an evening: Selcom callbacks kept being
 * rejected after the flag enabling them had reportedly been set, 177 went
 * unprocessed after a confirmed deploy, and there was no way from outside
 * to tell whether the process had ever seen the variable.
 *
 * `source` is what answers it. "env" means something supplied the value.
 * "default" means nothing did - which is exactly what a missing or
 * misspelled variable looks like from the inside, and is the state worth
 * noticing at a glance.
 *
 * Booleans and numbers only. The API never reports a secret here, in any
 * form.
 */

const LABELS: Record<string, string> = {
  environment: "Environment",
  selcom_checkout_accept_unsigned_callbacks: "Accept unsigned Selcom callbacks",
  selcom_checkout_reconcile_interval_seconds: "Collection reconcile interval (s)",
  selcom_disbursement_reconcile_interval_seconds: "Payout reconcile interval (s)",
  selcom_outbound_max_per_minute: "Selcom calls per minute",
  selcom_outbound_max_concurrent: "Selcom calls at once",
  selcom_reconcile_batch_size: "Reconcile batch size",
  collection_push_expiry_minutes: "Payment expiry (minutes)",
  webhook_delivery_interval_seconds: "Webhook delivery interval (s)",
  require_super_admin_mfa: "Require Super Admin 2FA",
  cache_enabled: "Cache enabled",
  oasis_sms_enabled: "SMS enabled",
};

function renderValue(value: EffectiveSettingsReport["settings"][string]["value"]) {
  if (typeof value === "boolean") {
    return (
      <span
        className={
          value
            ? "px-2 py-0.5 rounded-full bg-primary-container text-on-primary text-xs font-semibold"
            : "px-2 py-0.5 rounded-full bg-surface-container-highest text-on-surface-variant text-xs font-semibold"
        }
      >
        {value ? "on" : "off"}
      </span>
    );
  }
  return <span className="font-mono text-sm text-on-surface">{String(value)}</span>;
}

export function EffectiveSettingsCard({ report }: { report: EffectiveSettingsReport | null }) {
  return (
    <Card id="diagnostics" className="scroll-mt-24">
      <div className="mb-5">
        <h3 className="text-2xl font-semibold text-on-background">Live Configuration</h3>
        <p className="mt-1 text-sm text-on-surface-variant">
          What the running API actually resolved — not what the hosting dashboard was told.
          <span className="font-medium text-on-surface"> Set in Railway</span> means a variable
          supplied the value. <span className="font-medium text-on-surface">Default</span> means
          nothing did, which is what a missing or misspelled variable looks like.
        </p>
      </div>

      {report === null ? (
        <p className="text-sm text-error">
          Couldn&apos;t read the live configuration. That&apos;s a failed request, not an empty
          result — retry shortly.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-surface-container-highest">
                <th className="pb-2 text-xs font-semibold uppercase text-on-surface-variant">
                  Setting
                </th>
                <th className="pb-2 text-xs font-semibold uppercase text-on-surface-variant">
                  Value
                </th>
                <th className="pb-2 text-xs font-semibold uppercase text-on-surface-variant">
                  Source
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(report.settings).map(([name, entry]) => (
                <tr key={name} className="border-b border-surface-container-low last:border-0">
                  <td className="py-2.5 text-sm text-on-surface">
                    {LABELS[name] ?? name}
                    <span className="block font-mono text-[11px] text-on-surface-variant">
                      {name.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-2.5">{renderValue(entry.value)}</td>
                  <td className="py-2.5">
                    {entry.source === "env" ? (
                      <span className="text-xs font-medium text-on-surface-variant">
                        Set in Railway
                      </span>
                    ) : (
                      <span className="text-xs font-semibold text-error">Default — not set</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
