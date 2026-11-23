"use client";

import { useState } from "react";

import { Icon } from "@/components/portal/icon";
import { formatDateTime } from "@/lib/format";
import type { PaymentTracking } from "@/lib/portal/types";

/**
 * The payment / webhook / activation timeline, shared by the merchant's
 * transaction drawer and the Super Admin one so both read the same
 * evidence in the same words. `audience` only changes who "your server"
 * is: the merchant reading about their own endpoint, or an operator
 * reading about the merchant's.
 */
export type TrackingAudience = "merchant" | "admin";

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard blocked - the value is still selectable on screen */
        }
      }}
      className="shrink-0 rounded-md p-1 text-on-surface-variant hover:text-on-background hover:bg-surface-container"
      aria-label={copied ? `${label} copied` : `Copy ${label}`}
    >
      <Icon name={copied ? "check" : "content_copy"} className="text-[16px]" />
    </button>
  );
}

/** A reference with a sentence saying whose it is. Three references sit
 * next to each other here, and quoting the wrong one to a billing system
 * or to support is the mistake this layout exists to prevent. */
export function Reference({ label, value, hint, copy = false }: { label: string; value: string | null; hint: string; copy?: boolean }) {
  return (
    <div className="py-2.5 border-b border-surface-container-highest last:border-0">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-on-surface-variant shrink-0">{label}</span>
        <span className="flex items-center gap-1 min-w-0">
          <span className="text-sm font-mono text-on-background text-right break-all">{value ?? "Not available"}</span>
          {copy && value && <CopyButton value={value} label={label} />}
        </span>
      </div>
      <p className="mt-1 text-xs text-on-surface-variant">{hint}</p>
    </div>
  );
}

const STEP_ICON: Record<string, { icon: string; tone: string }> = {
  done: { icon: "check_circle", tone: "text-primary" },
  failed: { icon: "cancel", tone: "text-error" },
  waiting: { icon: "schedule", tone: "text-on-surface-variant" },
  unknown: { icon: "help", tone: "text-on-surface-variant" },
  delivered: { icon: "check_circle", tone: "text-primary" },
  queued: { icon: "schedule", tone: "text-on-surface-variant" },
  retrying: { icon: "sync_problem", tone: "text-on-surface-variant" },
  exhausted: { icon: "cancel", tone: "text-error" },
};

function Step({ state, title, children }: { state: string; title: string; children?: React.ReactNode }) {
  const { icon, tone } = STEP_ICON[state] ?? STEP_ICON.unknown;
  return (
    <li className="flex gap-3 py-2.5">
      <Icon name={icon} className={`${tone} text-[20px] shrink-0 mt-0.5`} />
      <div className="min-w-0">
        <p className="text-sm font-medium text-on-background">{title}</p>
        {children && <div className="mt-0.5 space-y-0.5 text-xs text-on-surface-variant">{children}</div>}
      </div>
    </li>
  );
}

function when(value: string | null): string {
  return value ? formatDateTime(value) : "Time not recorded";
}

export function TrackingTimeline({
  tracking,
  audience = "merchant",
}: {
  tracking: PaymentTracking;
  audience?: TrackingAudience;
}) {
  const server = audience === "merchant" ? "your server" : "the merchant’s server";
  const system = audience === "merchant" ? "Your system" : "The merchant’s system";
  const { webhooks } = tracking;
  return (
    <ol aria-label="Payment timeline" className="divide-y divide-surface-container-highest">
      {tracking.payment.map((step) => (
        <Step key={step.code} state={step.state} title={step.label}>
          {(step.at || step.state !== "waiting") && <p>{when(step.at)}</p>}
          {step.detail && <p>{step.detail}</p>}
        </Step>
      ))}

      {webhooks.applicable && !webhooks.available && (
        <Step state="unknown" title="Webhook delivery status unavailable">
          <p>The delivery record could not be loaded just now. Reopen this payment to try again.</p>
        </Step>
      )}
      {webhooks.applicable && webhooks.available && webhooks.deliveries.length === 0 && (
        <Step state="unknown" title={webhooks.configured ? "No webhook queued" : "No webhook endpoint configured"}>
          <p>
            {webhooks.configured
              ? "InfinityPay has no delivery record for this payment."
              : `${system} was not notified, because no webhook URL is set${audience === "merchant" ? " in Settings" : " for this merchant"}.`}
          </p>
        </Step>
      )}
      {webhooks.deliveries.map((delivery, index) => (
        <Step key={`${delivery.event_name}-${delivery.queued_at}-${index}`} state={delivery.state} title={delivery.label}>
          {delivery.event_name && <p className="font-mono">{delivery.event_name}</p>}
          <p>Queued {when(delivery.queued_at)}</p>
          {delivery.last_attempt_at && (
            <p>
              Attempt {delivery.attempts} of {delivery.max_attempts} at {formatDateTime(delivery.last_attempt_at)}
              {delivery.response_status !== null
                ? ` — ${server} answered HTTP ${delivery.response_status}`
                : ` — no response from ${server}`}
            </p>
          )}
          {delivery.state === "delivered" && delivery.delivered_at && (
            <p>Received by {server} {formatDateTime(delivery.delivered_at)}</p>
          )}
          {delivery.next_retry_at && <p>Next attempt around {formatDateTime(delivery.next_retry_at)}</p>}
          {delivery.state === "exhausted" && <p>No further automatic attempts will be made.</p>}
        </Step>
      ))}

      {webhooks.applicable && (
        <Step state="unknown" title={tracking.service_activation.label}>
          <p>
            {audience === "merchant"
              ? tracking.service_activation.detail
              : "InfinityPay records whether the merchant’s system received the notification, not whether it activated the customer’s service. The merchant’s billing system controls activation."}
          </p>
          {/* Said in so many words, because it is the misreading that
            * matters: "Webhook delivered" next to a customer with no
            * internet looks like our fault or like theirs, and it is
            * neither proof. */}
          <p>A delivered webhook means {server} received the notification (HTTP 2xx), not that the customer&apos;s service was activated.</p>
        </Step>
      )}
    </ol>
  );
}

