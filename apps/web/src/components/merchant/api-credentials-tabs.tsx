"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";

import { ApiCredentialsOverview } from "./api-credentials-overview";
import { ApiKeysView } from "./api-keys-view";
import { ApiLogsView } from "./api-logs-view";
import { DeveloperDocsView } from "./developer-docs-view";
import { IpAllowlistView } from "./ip-allowlist-view";
import { WebhooksView } from "./webhooks-view";

export type ApiCredentialsTab = "overview" | "keys" | "webhooks" | "ip-allowlist" | "logs" | "docs";

const TABS: { value: ApiCredentialsTab; label: string; icon: string }[] = [
  { value: "overview", label: "Overview", icon: "space_dashboard" },
  { value: "keys", label: "API Keys", icon: "vpn_key" },
  { value: "webhooks", label: "Webhooks", icon: "webhook" },
  { value: "ip-allowlist", label: "IP Allowlist", icon: "shield_lock" },
  { value: "logs", label: "API Logs", icon: "history_toggle_off" },
  { value: "docs", label: "Developer Docs", icon: "menu_book" },
];

function isValidTab(value: string | null): value is ApiCredentialsTab {
  return TABS.some((tab) => tab.value === value);
}

export function ApiCredentialsTabs({ initialTab }: { initialTab?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fromUrl = searchParams.get("tab");
  const [activeTab, setActiveTab] = useState<ApiCredentialsTab>(
    isValidTab(fromUrl) ? fromUrl : isValidTab(initialTab ?? null) ? (initialTab as ApiCredentialsTab) : "overview",
  );

  function selectTab(tab: ApiCredentialsTab) {
    setActiveTab(tab);
    router.replace(`/portal/api-credentials?tab=${tab}`, { scroll: false });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="API Credentials"
        description="Everything for integrating your website, mobile app, or backend with InfinityPay — in one place."
      />

      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-6 items-start">
        {/* Horizontal scroll row on mobile/tablet; a vertical, individually
            bordered menu — Infinity green on the active item — from lg
            upward, sized to its own 240px grid column. */}
        <nav
          role="tablist"
          aria-label="API Credentials sections"
          className="flex flex-nowrap gap-0.5 rounded-lg border border-surface-container-highest bg-surface-container-low p-1 overflow-x-auto lg:flex-col lg:gap-1.5 lg:overflow-visible lg:rounded-none lg:border-0 lg:bg-transparent lg:p-0"
        >
          {TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.value}
              onClick={() => selectTab(tab.value)}
              className={`flex items-center gap-1 lg:gap-2.5 px-2.5 py-1.5 lg:px-4 lg:py-2.5 rounded-md lg:rounded-lg text-sm font-medium whitespace-nowrap shrink-0 lg:w-full lg:border transition-colors ${
                activeTab === tab.value
                  ? "bg-primary-container text-on-primary lg:border-primary-container"
                  : "text-on-surface-variant hover:bg-surface-container-highest lg:border-surface-container-highest lg:bg-surface"
              }`}
            >
              <Icon name={tab.icon} className="text-[16px] lg:text-[18px] shrink-0" />
              {tab.label}
            </button>
          ))}
        </nav>

        <div role="tabpanel" className="min-w-0">
          {activeTab === "overview" && <ApiCredentialsOverview onSelectTab={selectTab} />}
          {activeTab === "keys" && <ApiKeysView />}
          {activeTab === "webhooks" && <WebhooksView />}
          {activeTab === "ip-allowlist" && <IpAllowlistView />}
          {activeTab === "logs" && <ApiLogsView />}
          {activeTab === "docs" && <DeveloperDocsView />}
        </div>
      </div>
    </div>
  );
}
