"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { getMyMerchant, getWebhookConfig, listApiKeys, listApiLogs, listIpAllowlist } from "@/lib/portal/api";
import type { ApiKey, ApiRequestLog, IpAllowlistEntry, MerchantProfile, WebhookConfig } from "@/lib/portal/types";

import type { ApiCredentialsTab } from "./api-credentials-tabs";

interface ChecklistItem {
  label: string;
  icon: string;
  done: boolean;
  tab: ApiCredentialsTab;
}

export function ApiCredentialsOverview({ onSelectTab }: { onSelectTab: (tab: ApiCredentialsTab) => void }) {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [webhookConfig, setWebhookConfig] = useState<WebhookConfig | null>(null);
  const [ipEntries, setIpEntries] = useState<IpAllowlistEntry[]>([]);
  const [logs, setLogs] = useState<ApiRequestLog[]>([]);
  const [docsVisited, setDocsVisited] = useState(false);
  const [merchant, setMerchant] = useState<MerchantProfile | null>(null);

  useEffect(() => {
    listApiKeys().then(setKeys);
    getWebhookConfig().then(setWebhookConfig);
    listIpAllowlist().then(setIpEntries);
    listApiLogs().then(setLogs);
    getMyMerchant().then(setMerchant);
  }, []);

  const loading = keys === null;
  const activeKeys = keys?.filter((k) => k.status === "active") ?? [];
  const sandboxCount = activeKeys.filter((k) => k.environment === "sandbox").length;
  const productionCount = activeKeys.filter((k) => k.environment === "live").length;
  const anySandboxUsed = activeKeys.some((k) => k.environment === "sandbox" && k.last_used_at);
  const anyLiveKey = productionCount > 0;
  const lastRequest = logs[0] ?? null;

  const integrationStatus = loading
    ? null
    : productionCount > 0
      ? { label: "Live", tone: "positive" as const }
      : sandboxCount > 0
        ? { label: "Sandbox only", tone: "pending" as const }
        : { label: "Not started", tone: "neutral" as const };

  const summary = loading
    ? "Loading your integration status…"
    : productionCount > 0
      ? `You have ${sandboxCount} sandbox and ${productionCount} production key${productionCount === 1 ? "" : "s"} active, with ${ipEntries.length} IP${ipEntries.length === 1 ? "" : "s"} on the allowlist. ${webhookConfig?.webhook_url ? "Webhooks are configured." : "No webhook URL configured yet."}`
      : sandboxCount > 0
        ? `You have ${sandboxCount} sandbox key${sandboxCount === 1 ? "" : "s"} active. Create a production key once your account is approved to go live.`
        : "You haven't created an API key yet — generate a sandbox key below to start building your integration.";

  const checklist: ChecklistItem[] = [
    { label: "Create API key", icon: "vpn_key", done: (keys?.length ?? 0) > 0, tab: "keys" },
    { label: "Add webhook URL", icon: "webhook", done: Boolean(webhookConfig?.webhook_url), tab: "webhooks" },
    {
      label: "Add IP allowlist or continue without whitelist",
      icon: "shield_lock",
      done: (keys?.length ?? 0) > 0,
      tab: "ip-allowlist",
    },
    { label: "Read developer docs", icon: "menu_book", done: docsVisited, tab: "docs" },
    { label: "Test sandbox integration", icon: "science", done: anySandboxUsed, tab: "keys" },
    { label: "Go live", icon: "rocket_launch", done: anyLiveKey, tab: "keys" },
  ];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        description="Your API integration at a glance — keys, webhooks, IP protection, and what's left to set up."
        action={
          merchant?.merchant_code ? (
            <p className="text-xs text-on-surface-variant">
              ID: <span className="font-mono font-semibold text-on-background">{merchant.merchant_code}</span>
            </p>
          ) : undefined
        }
      />

      <Card>
        <div className="flex items-start gap-4">
          {integrationStatus && <StatusBadge label={integrationStatus.label} tone={integrationStatus.tone} dot />}
        </div>
        <p className="mt-4 text-sm text-on-surface-variant leading-relaxed">{summary}</p>
        <p className="mt-2 text-xs text-on-surface-variant">
          Last API request:{" "}
          {lastRequest ? (
            <>
              <span className="font-mono">
                {lastRequest.method} {lastRequest.path}
              </span>{" "}
              — {formatDateTime(lastRequest.created_at)}
            </>
          ) : (
            "none yet"
          )}
        </p>
      </Card>

      <Card>
        <h3 className="text-lg font-semibold text-on-surface mb-4">Quick Setup Checklist</h3>
        <ul className="space-y-1">
          {checklist.map((item) => (
            <li key={item.label}>
              <button
                type="button"
                onClick={() => {
                  if (item.tab === "docs") setDocsVisited(true);
                  onSelectTab(item.tab);
                }}
                className="w-full flex items-center gap-3 rounded-lg px-3 py-3 text-sm text-on-surface hover:bg-surface-container transition-colors text-left"
              >
                <Icon
                  name={item.done ? "check_circle" : item.icon}
                  className={`text-[20px] ${item.done ? "text-primary" : "text-primary-container"}`}
                />
                {item.label}
                <Icon name="arrow_forward" className="ml-auto text-[16px] text-outline shrink-0" />
              </button>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
