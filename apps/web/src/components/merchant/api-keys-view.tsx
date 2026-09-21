"use client";

import { Fragment, useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { EmptyState } from "@/components/portal/empty-state";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { SegmentedControl } from "@/components/portal/segmented-control";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import {
  createApiKey,
  createIpAllowlistEntry,
  deleteIpAllowlistEntry,
  getMyMerchant,
  listApiKeys,
  listIpAllowlist,
  renameApiKey,
  revokeApiKey,
  rotateApiKey,
  updateApiKeyIpWhitelist,
} from "@/lib/portal/api";
import { API_KEY_SCOPES, type AllowedIpDraft, type ApiKey, type ApiKeyScope, type IpAllowlistEntry } from "@/lib/portal/types";

// IPv4 dotted-quad, optionally with a /0-32 CIDR suffix — the only format
// the backend accepts (app.schemas.ip_allowlist._validate_ip_or_cidr uses
// Python's ipaddress module, which is stricter about IPv6 shorthand than a
// hand-written regex could safely match, so this client-side check only
// needs to catch the common IPv4 case early; the server is the real check).
const IPV4_OCTET = "(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])";
const IPV4_ADDRESS_RE = new RegExp(`^${IPV4_OCTET}(\\.${IPV4_OCTET}){3}$`);
const IPV4_CIDR_RE = new RegExp(`^${IPV4_OCTET}(\\.${IPV4_OCTET}){3}/(3[0-2]|[12]?[0-9])$`);

function isValidIpOrCidr(value: string): boolean {
  return IPV4_ADDRESS_RE.test(value) || IPV4_CIDR_RE.test(value);
}

const SCOPE_LABELS: Record<ApiKeyScope, string> = {
  "collections:write": "Collections — create",
  "collections:read": "Collections — view",
  "payment_links:write": "Payment Links — create",
  "payment_links:read": "Payment Links — view",
  "invoices:write": "Invoices — create",
  "invoices:read": "Invoices — view",
  "transactions:read": "Transactions — view",
  "webhooks:manage": "Webhooks — manage",
};

const STEPS = [
  { step: 1, title: "Generate a key", description: "Create a sandbox key with only the scopes you need." },
  { step: 2, title: "Read the docs", description: "Explore endpoints for payment links, invoices, and payouts." },
  { step: 3, title: "Make your first request", description: "Send a test transaction and confirm the webhook fires." },
];

export function ApiKeysView() {
  const [environment, setEnvironment] = useState<"sandbox" | "live">("sandbox");
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [rotatingId, setRotatingId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [scopes, setScopes] = useState<ApiKeyScope[]>([]);
  const [ipWhitelistChoice, setIpWhitelistChoice] = useState<"enabled" | "continue_without">("continue_without");
  const [allowedIps, setAllowedIps] = useState<AllowedIpDraft[]>([]);
  const [ipInputValue, setIpInputValue] = useState("");
  const [ipLabelInputValue, setIpLabelInputValue] = useState("");
  const [ipFormError, setIpFormError] = useState<string | null>(null);
  const [merchantApproved, setMerchantApproved] = useState<boolean | null>(null);
  const [apiSuspended, setApiSuspended] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // Per-key "Manage IPs" panel (API key detail: linked allowed IPs, add/
  // remove, and switching Enable/Continue-without after creation).
  const [expandedKeyId, setExpandedKeyId] = useState<string | null>(null);
  const [expandedIps, setExpandedIps] = useState<IpAllowlistEntry[]>([]);
  const [expandedLoading, setExpandedLoading] = useState(false);
  const [expandedIpInput, setExpandedIpInput] = useState("");
  const [expandedLabelInput, setExpandedLabelInput] = useState("");
  const [expandedError, setExpandedError] = useState<string | null>(null);
  const [expandedToggling, setExpandedToggling] = useState(false);

  const visibleKeys = keys.filter((key) => key.environment === environment);
  // Self-service production: a merchant creates their own Live key the
  // moment they're approved + KYC-verified — no separate Super Admin
  // "enable production" step. This banner reflects only the part known
  // client-side (approval/KYC); a pricing-rule gap or a suspension surfaces
  // through the server's own rejection message in generateError instead.
  const liveBlocked = environment === "live" && merchantApproved === false;
  const ipWhitelistMissingIps = ipWhitelistChoice === "enabled" && allowedIps.length === 0;

  useEffect(() => {
    listApiKeys().then(setKeys);
    getMyMerchant().then((merchant) => {
      if (!merchant) return;
      setMerchantApproved(merchant.status === "active" && merchant.kyc_status === "verified");
      setApiSuspended(merchant.api_access_suspended);
    });
  }, []);

  function toggleScope(scope: ApiKeyScope) {
    setScopes((prev) => (prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]));
  }

  function handleAddIp() {
    // Supports one IP at a time, or pasting several separated by commas
    // and/or newlines in one go.
    const candidates = ipInputValue
      .split(/[,\n]/)
      .map((v) => v.trim())
      .filter(Boolean);

    if (candidates.length === 0) return;

    const existing = new Set(allowedIps.map((entry) => entry.ip_address_or_cidr.toLowerCase()));
    const toAdd: AllowedIpDraft[] = [];
    const invalid: string[] = [];
    const duplicates: string[] = [];
    const label = candidates.length === 1 ? ipLabelInputValue.trim() || null : null;

    for (const candidate of candidates) {
      if (!isValidIpOrCidr(candidate)) {
        invalid.push(candidate);
        continue;
      }
      const key = candidate.toLowerCase();
      if (existing.has(key) || toAdd.some((e) => e.ip_address_or_cidr.toLowerCase() === key)) {
        duplicates.push(candidate);
        continue;
      }
      toAdd.push({ ip_address_or_cidr: candidate, label });
    }

    if (toAdd.length > 0) {
      setAllowedIps((prev) => [...prev, ...toAdd]);
    }

    if (invalid.length > 0) {
      setIpFormError(`Invalid IP address or CIDR: ${invalid.join(", ")}`);
    } else if (duplicates.length > 0) {
      setIpFormError(`Already added: ${duplicates.join(", ")}`);
    } else {
      setIpFormError(null);
    }

    // Only clear the inputs once everything typed was actually accepted —
    // otherwise the merchant would lose whatever they need to go fix.
    if (invalid.length === 0 && duplicates.length === 0) {
      setIpInputValue("");
      setIpLabelInputValue("");
    }
  }

  function handleRemoveIp(index: number) {
    setAllowedIps((prev) => prev.filter((_, i) => i !== index));
  }

  async function loadExpandedIps(keyId: string) {
    setExpandedLoading(true);
    try {
      setExpandedIps(await listIpAllowlist({ apiKeyId: keyId }));
    } finally {
      setExpandedLoading(false);
    }
  }

  async function toggleExpandKey(key: ApiKey) {
    if (expandedKeyId === key.id) {
      setExpandedKeyId(null);
      return;
    }
    setExpandedKeyId(key.id);
    setExpandedError(null);
    setExpandedIpInput("");
    setExpandedLabelInput("");
    await loadExpandedIps(key.id);
  }

  async function handleAddExpandedIp(key: ApiKey) {
    const ip = expandedIpInput.trim();
    if (!ip) return;
    if (!isValidIpOrCidr(ip)) {
      setExpandedError(`Invalid IP address or CIDR: ${ip}`);
      return;
    }
    if (expandedIps.some((entry) => entry.ip_address_or_cidr.toLowerCase() === ip.toLowerCase())) {
      setExpandedError(`Already added: ${ip}`);
      return;
    }
    setExpandedError(null);
    await createIpAllowlistEntry({
      environment: key.environment,
      label: expandedLabelInput.trim() || ip,
      ip_address_or_cidr: ip,
      api_key_id: key.id,
    });
    setExpandedIpInput("");
    setExpandedLabelInput("");
    await loadExpandedIps(key.id);
  }

  async function handleRemoveExpandedIp(key: ApiKey, entryId: string) {
    await deleteIpAllowlistEntry(entryId);
    await loadExpandedIps(key.id);
  }

  async function handleToggleKeyIpWhitelist(key: ApiKey) {
    const enabling = !key.ip_whitelist_enabled;
    if (enabling && expandedIps.filter((e) => e.status !== "rejected").length === 0) {
      setExpandedError("Add at least one allowed server IP or choose Continue without IP whitelisting.");
      return;
    }
    setExpandedToggling(true);
    setExpandedError(null);
    try {
      const updated = await updateApiKeyIpWhitelist(key.id, enabling);
      setKeys((prev) => prev.map((k) => (k.id === key.id ? updated : k)));
    } catch (err) {
      setExpandedError(err instanceof Error ? err.message : "Couldn't update IP whitelisting for this key.");
    } finally {
      setExpandedToggling(false);
    }
  }

  async function handleGenerate(event: React.FormEvent) {
    event.preventDefault();
    if (!keyName.trim() || scopes.length === 0 || ipWhitelistMissingIps) return;

    setGenerating(true);
    setGenerateError(null);
    try {
      const { key, plaintext_key } = await createApiKey({
        name: keyName.trim(),
        environment,
        scopes,
        ip_whitelist_enabled: ipWhitelistChoice === "enabled",
        continue_without_ip_whitelist: ipWhitelistChoice === "continue_without",
        allowed_ips: ipWhitelistChoice === "enabled" ? allowedIps : undefined,
      });
      setKeys((prev) => [key, ...prev]);
      setRevealed(plaintext_key);
      setCopied(false);
      setFormOpen(false);
      setKeyName("");
      setScopes([]);
      setIpWhitelistChoice("continue_without");
      setAllowedIps([]);
      setIpInputValue("");
      setIpLabelInputValue("");
      setIpFormError(null);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Couldn't generate this API key.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleRename(keyId: string) {
    const name = renameValue.trim();
    if (!name) return;
    const updated = await renameApiKey(keyId, name);
    setKeys((prev) => prev.map((k) => (k.id === keyId ? updated : k)));
    setRenamingId(null);
  }

  async function handleCopy() {
    if (!revealed) return;
    await navigator.clipboard?.writeText(revealed);
    setCopied(true);
  }

  async function handleRevoke(keyId: string) {
    setRevokingId(keyId);
    try {
      const revoked = await revokeApiKey(keyId);
      setKeys((prev) => prev.map((k) => (k.id === keyId ? revoked : k)));
    } finally {
      setRevokingId(null);
    }
  }

  async function handleRotate(keyId: string) {
    setRotatingId(keyId);
    try {
      const { key, plaintext_key } = await rotateApiKey(keyId);
      setKeys((prev) => [key, ...prev.map((k) => (k.id === keyId ? { ...k, status: "revoked" as const } : k))]);
      setRevealed(plaintext_key);
      setCopied(false);
    } finally {
      setRotatingId(null);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="API Keys"
        description="Manage sandbox and live keys to integrate InfinityPay into your app."
        action={
          <SegmentedControl
            options={[
              { value: "sandbox" as const, label: "Sandbox" },
              { value: "live" as const, label: "Live" },
            ]}
            value={environment}
            onChange={(value) => {
              setEnvironment(value);
              setRevealed(null);
            }}
          />
        }
      />

      <div className="flex items-start gap-3 rounded-lg border border-primary/30 bg-primary-container/10 px-4 py-3.5">
        <Icon name="warning" className="text-[20px] text-primary shrink-0 mt-0.5" />
        <p className="text-sm text-on-background">
          <span className="font-semibold">Use secret keys only on your backend.</span> Never expose them in
          frontend or mobile apps — anyone who sees your source code, a browser DevTools request, or an
          unpacked app bundle can read a key embedded there. Have your client app call your own backend, and
          have your backend call InfinityPay.
        </p>
      </div>

      {apiSuspended && (
        <div className="flex items-start gap-3 rounded-lg border border-error/30 bg-error-container/30 px-4 py-3.5">
          <Icon name="block" className="text-[20px] text-error shrink-0 mt-0.5" />
          <p className="text-sm text-on-error-container">
            <span className="font-semibold">API access is currently suspended</span> for this account. Existing and
            new keys will not authenticate. Contact InfinityPay support.
          </p>
        </div>
      )}

      {!apiSuspended && liveBlocked && (
        <div className="flex items-start gap-3 rounded-lg border border-outline-variant bg-surface-container-low px-4 py-3.5">
          <Icon name="lock" className="text-[20px] text-on-surface-variant shrink-0 mt-0.5" />
          <p className="text-sm text-on-surface-variant">
            <span className="font-semibold text-on-background">
              Production API keys are available after your business account is approved.
            </span>{" "}
            You can still create and use Sandbox keys in the meantime — no approval needed for those.
          </p>
        </div>
      )}

      {revealed && (
        <Card className="border-primary">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h3 className="text-lg font-semibold text-on-background mb-1">Your new API key</h3>
              <p className="text-sm text-error font-medium mb-3">
                Copy this key now. You will not be able to view it again.
              </p>
              <code className="block bg-on-surface text-primary-fixed text-sm px-4 py-3 rounded-lg font-mono break-all">
                {revealed}
              </code>
            </div>
            <button
              type="button"
              onClick={handleCopy}
              className="shrink-0 p-2.5 bg-primary-container/10 text-primary rounded-lg hover:bg-primary-container/20 transition-colors"
              title="Copy key"
            >
              <Icon name={copied ? "check" : "content_copy"} className="text-[20px]" />
            </button>
          </div>
        </Card>
      )}

      {formOpen && (
        <Card>
          <form onSubmit={handleGenerate} className="space-y-5">
            <h3 className="text-2xl font-semibold text-on-background">
              Generate {environment === "sandbox" ? "Sandbox" : "Live"} Key
            </h3>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Key Name</label>
              <input
                className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                placeholder="e.g. Website checkout integration"
                type="text"
                value={keyName}
                onChange={(event) => setKeyName(event.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-2">Scopes</label>
              <div className="grid sm:grid-cols-2 gap-2.5">
                {API_KEY_SCOPES.map((scope) => (
                  <label
                    key={scope}
                    className="flex items-center gap-2.5 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg cursor-pointer"
                  >
                    <input
                      checked={scopes.includes(scope)}
                      onChange={() => toggleScope(scope)}
                      className="rounded border-outline-variant text-primary-container focus:ring-primary"
                      type="checkbox"
                    />
                    <span className="text-sm font-medium text-on-surface">{SCOPE_LABELS[scope]}</span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-2">IP Whitelisting</label>
              <div className="space-y-2">
                <label className="flex items-start gap-2.5 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg cursor-pointer">
                  <input
                    checked={ipWhitelistChoice === "continue_without"}
                    onChange={() => setIpWhitelistChoice("continue_without")}
                    className="mt-0.5 text-primary-container focus:ring-primary"
                    type="radio"
                    name="ip_whitelist_choice"
                  />
                  <span className="text-sm">
                    <span className="font-medium text-on-surface">Continue without IP whitelisting</span>
                    <span className="block text-xs text-on-surface-variant mt-0.5">
                      Accept this key from any server IP.{" "}
                      {environment === "live" && "For production, IP whitelisting is recommended for stronger security."}
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-2.5 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg cursor-pointer">
                  <input
                    checked={ipWhitelistChoice === "enabled"}
                    onChange={() => setIpWhitelistChoice("enabled")}
                    className="mt-0.5 text-primary-container focus:ring-primary"
                    type="radio"
                    name="ip_whitelist_choice"
                  />
                  <span className="text-sm">
                    <span className="font-medium text-on-surface">Enable IP whitelisting</span>
                    <span className="block text-xs text-on-surface-variant mt-0.5">
                      Only accept this key from server IPs you approve, added below.
                    </span>
                  </span>
                </label>
              </div>

              {ipWhitelistChoice === "enabled" && (
                <div className="mt-3 rounded-lg border border-surface-container-highest bg-surface-container-lowest p-4 space-y-3">
                  <p className="text-sm font-medium text-on-surface">Allowed server IPs</p>
                  <div className="flex flex-col sm:flex-row gap-2.5">
                    <input
                      className="flex-1 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm font-mono"
                      placeholder="Enter server IP address or CIDR"
                      type="text"
                      value={ipInputValue}
                      onChange={(event) => setIpInputValue(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          handleAddIp();
                        }
                      }}
                    />
                    <input
                      className="sm:w-56 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                      placeholder="Label, e.g. Main ecommerce server"
                      type="text"
                      value={ipLabelInputValue}
                      onChange={(event) => setIpLabelInputValue(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          handleAddIp();
                        }
                      }}
                    />
                    <button
                      type="button"
                      onClick={handleAddIp}
                      disabled={!ipInputValue.trim()}
                      className="shrink-0 bg-primary-container text-on-primary text-sm font-medium py-2.5 px-4 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
                    >
                      Add IP
                    </button>
                  </div>
                  <p className="text-xs text-on-surface-variant">
                    41.59.10.20 for a single address, or 41.59.10.20/32 (CIDR) for a range. Paste several at once
                    separated by commas or new lines.
                  </p>
                  {ipFormError && <p className="text-sm text-error">{ipFormError}</p>}

                  {allowedIps.length > 0 && (
                    <div className="overflow-x-auto rounded-lg border border-surface-container-highest">
                      <table className="w-full text-left text-sm">
                        <thead>
                          <tr className="text-on-surface-variant text-xs font-semibold bg-surface-container-low">
                            <th className="px-3 py-2">IP / CIDR</th>
                            <th className="px-3 py-2">Label</th>
                            <th className="px-3 py-2 text-right">Remove</th>
                          </tr>
                        </thead>
                        <tbody>
                          {allowedIps.map((entry, index) => (
                            <tr key={`${entry.ip_address_or_cidr}-${index}`} className="border-t border-surface-container-highest">
                              <td className="px-3 py-2 font-mono text-xs text-on-background">{entry.ip_address_or_cidr}</td>
                              <td className="px-3 py-2 text-on-surface-variant text-xs">{entry.label ?? "—"}</td>
                              <td className="px-3 py-2 text-right">
                                <button
                                  type="button"
                                  onClick={() => handleRemoveIp(index)}
                                  className="text-error text-xs font-semibold hover:underline"
                                >
                                  Remove
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {ipWhitelistMissingIps && (
                    <p className="text-sm text-error">
                      Add at least one allowed server IP or choose Continue without IP whitelisting.
                    </p>
                  )}
                </div>
              )}
            </div>
            {generateError && <p className="text-sm text-error">{generateError}</p>}
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={
                  generating ||
                  !keyName.trim() ||
                  scopes.length === 0 ||
                  liveBlocked ||
                  apiSuspended ||
                  ipWhitelistMissingIps
                }
                title={
                  apiSuspended
                    ? "API access is suspended for this account"
                    : liveBlocked
                      ? "Production API keys are available after your business account is approved"
                      : ipWhitelistMissingIps
                        ? "Add at least one allowed server IP or choose Continue without IP whitelisting."
                        : undefined
                }
                className="bg-primary-container text-on-primary text-sm font-medium py-2.5 px-5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
              >
                {generating ? "Generating…" : "Generate API Key"}
              </button>
              <button
                type="button"
                onClick={() => setFormOpen(false)}
                className="text-sm font-medium text-on-surface-variant hover:text-on-background"
              >
                Cancel
              </button>
            </div>
          </form>
        </Card>
      )}

      {visibleKeys.length === 0 ? (
        <Card>
          <EmptyState
            icon="vpn_key"
            heading="No API keys yet"
            body="Generate your first sandbox key to start testing the InfinityPay API — switch to Live once you're ready to go into production."
            actionLabel="Generate API Key"
            onAction={() => setFormOpen(true)}
          />
        </Card>
      ) : (
        <Card padded={false}>
          <div className="flex items-center justify-between p-5 pb-3">
            <h3 className="text-2xl font-semibold text-on-background">{environment === "sandbox" ? "Sandbox" : "Live"} Keys</h3>
            {!formOpen && (
              <button
                type="button"
                onClick={() => setFormOpen(true)}
                className="bg-primary-container text-on-primary text-sm font-medium py-2 px-4 rounded-lg hover:opacity-90 transition-opacity"
              >
                Generate API Key
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[1050px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Name</th>
                  <th className={thClass}>Key</th>
                  <th className={thClass}>IP Whitelist</th>
                  <th className={thClass}>Scopes</th>
                  <th className={thClass}>Created</th>
                  <th className={thClass}>Last Used</th>
                  <th className={thClass}>Status</th>
                  <th className={`${thClass} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {visibleKeys.map((key) => (
                  <Fragment key={key.id}>
                  <tr className="border-t border-surface-container-highest">
                    <td className={`${tdClass} font-medium text-on-background`}>
                      {renamingId === key.id ? (
                        <div className="flex items-center gap-2">
                          <input
                            autoFocus
                            value={renameValue}
                            onChange={(event) => setRenameValue(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") handleRename(key.id);
                              if (event.key === "Escape") setRenamingId(null);
                            }}
                            className="px-2 py-1 bg-surface-container-low border border-surface-container-highest rounded text-sm w-40"
                          />
                          <button type="button" onClick={() => handleRename(key.id)} className="text-primary text-xs font-semibold">
                            Save
                          </button>
                          <button type="button" onClick={() => setRenamingId(null)} className="text-on-surface-variant text-xs">
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setRenamingId(key.id);
                            setRenameValue(key.name);
                          }}
                          className="hover:underline text-left"
                          title="Rename this key"
                        >
                          {key.name}
                        </button>
                      )}
                    </td>
                    <td className={`${tdClass} font-mono text-xs`}>
                      {key.key_prefix}••••••••{key.key_last4 ?? ""}
                    </td>
                    <td className={tdClass}>
                      <button type="button" onClick={() => toggleExpandKey(key)} className="hover:opacity-80">
                        <StatusBadge
                          label={key.ip_whitelist_enabled ? "Enabled" : "Any IP"}
                          tone={key.ip_whitelist_enabled ? "positive" : "neutral"}
                          dot
                        />
                      </button>
                    </td>
                    <td className={tdClass}>
                      <div className="flex flex-wrap gap-1 max-w-[220px]">
                        {key.scopes.length === 0 ? (
                          <span className="text-xs text-on-surface-variant">No scopes</span>
                        ) : (
                          key.scopes.map((scope) => (
                            <span
                              key={scope}
                              className="text-[11px] font-medium bg-surface-container-low border border-surface-container-highest rounded px-1.5 py-0.5"
                            >
                              {scope}
                            </span>
                          ))
                        )}
                      </div>
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(key.created_at)}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>
                      {key.last_used_at ? formatDateTime(key.last_used_at) : "Never"}
                    </td>
                    <td className={tdClass}>
                      <StatusBadge
                        label={key.status === "active" ? "Active" : "Revoked"}
                        tone={key.status === "active" ? "positive" : "negative"}
                        dot
                      />
                    </td>
                    <td className={`${tdClass} text-right`}>
                      {key.status === "active" && (
                        <div className="flex items-center justify-end gap-3">
                          <button
                            type="button"
                            onClick={() => toggleExpandKey(key)}
                            className="text-on-surface-variant text-xs font-semibold hover:underline"
                          >
                            {expandedKeyId === key.id ? "Hide IPs" : "Manage IPs"}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleRotate(key.id)}
                            disabled={rotatingId === key.id || revokingId === key.id}
                            className="text-primary text-xs font-semibold hover:underline disabled:opacity-60"
                            title="Revoke this key and generate a replacement with the same name and scopes"
                          >
                            {rotatingId === key.id ? "Rotating…" : "Rotate"}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleRevoke(key.id)}
                            disabled={revokingId === key.id || rotatingId === key.id}
                            className="text-error text-xs font-semibold hover:underline disabled:opacity-60"
                          >
                            {revokingId === key.id ? "Revoking…" : "Revoke"}
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                  {expandedKeyId === key.id && (
                    <tr className="border-t border-surface-container-highest bg-surface-container-lowest">
                      <td colSpan={8} className="px-5 py-4">
                        <div className="max-w-2xl space-y-3">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-semibold text-on-background">
                              Allowed IPs for &ldquo;{key.name}&rdquo;
                            </p>
                            <button
                              type="button"
                              onClick={() => handleToggleKeyIpWhitelist(key)}
                              disabled={expandedToggling}
                              className="text-xs font-semibold text-primary hover:underline disabled:opacity-60"
                            >
                              {expandedToggling
                                ? "Updating…"
                                : key.ip_whitelist_enabled
                                  ? "Switch to Continue without IP whitelisting"
                                  : "Switch to Enable IP whitelisting"}
                            </button>
                          </div>

                          {expandedLoading ? (
                            <p className="text-sm text-on-surface-variant">Loading…</p>
                          ) : (
                            <>
                              {expandedIps.length === 0 ? (
                                <p className="text-sm text-on-surface-variant">No IPs linked to this key yet.</p>
                              ) : (
                                <div className="overflow-x-auto rounded-lg border border-surface-container-highest">
                                  <table className="w-full text-left text-sm bg-surface">
                                    <thead>
                                      <tr className="text-on-surface-variant text-xs font-semibold bg-surface-container-low">
                                        <th className="px-3 py-2">IP / CIDR</th>
                                        <th className="px-3 py-2">Label</th>
                                        <th className="px-3 py-2">Status</th>
                                        <th className="px-3 py-2 text-right">Remove</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {expandedIps.map((entry) => (
                                        <tr key={entry.id} className="border-t border-surface-container-highest">
                                          <td className="px-3 py-2 font-mono text-xs text-on-background">
                                            {entry.ip_address_or_cidr}
                                          </td>
                                          <td className="px-3 py-2 text-on-surface-variant text-xs">{entry.label}</td>
                                          <td className="px-3 py-2">
                                            <StatusBadge
                                              label={entry.status}
                                              tone={
                                                entry.status === "active"
                                                  ? "positive"
                                                  : entry.status === "pending"
                                                    ? "pending"
                                                    : "negative"
                                              }
                                            />
                                          </td>
                                          <td className="px-3 py-2 text-right">
                                            <button
                                              type="button"
                                              onClick={() => handleRemoveExpandedIp(key, entry.id)}
                                              className="text-error text-xs font-semibold hover:underline"
                                            >
                                              Remove
                                            </button>
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}

                              <div className="flex flex-col sm:flex-row gap-2.5">
                                <input
                                  className="flex-1 px-3.5 py-2 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm font-mono"
                                  placeholder="Enter server IP address or CIDR"
                                  type="text"
                                  value={expandedIpInput}
                                  onChange={(event) => setExpandedIpInput(event.target.value)}
                                />
                                <input
                                  className="sm:w-56 px-3.5 py-2 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm"
                                  placeholder="Label, e.g. Main ecommerce server"
                                  type="text"
                                  value={expandedLabelInput}
                                  onChange={(event) => setExpandedLabelInput(event.target.value)}
                                />
                                <button
                                  type="button"
                                  onClick={() => handleAddExpandedIp(key)}
                                  disabled={!expandedIpInput.trim()}
                                  className="shrink-0 bg-primary-container text-on-primary text-sm font-medium py-2 px-4 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
                                >
                                  Add IP
                                </button>
                              </div>
                              {expandedError && <p className="text-sm text-error">{expandedError}</p>}
                              <p className="text-xs text-on-surface-variant">
                                New IPs start pending until InfinityPay approves them.
                              </p>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card>
        <h3 className="text-2xl font-semibold text-on-background mb-5">Quick Start</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-5 mb-6">
          {STEPS.map((item) => (
            <div key={item.step}>
              <div className="w-8 h-8 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-sm mb-3">
                {item.step}
              </div>
              <h4 className="font-semibold text-on-background text-sm mb-1">{item.title}</h4>
              <p className="text-sm text-on-surface-variant">{item.description}</p>
            </div>
          ))}
        </div>
        <pre className="bg-on-surface text-primary-fixed text-xs sm:text-sm rounded-lg p-4 overflow-x-auto">
          <span className="text-white/40">curl</span> https://api.infinitypay.me/v1/payment-links \{"\n"}
          {"  "}-H &quot;Authorization: Bearer inf_live_••••••••&quot; \{"\n"}
          {"  "}-H &quot;Content-Type: application/json&quot;
        </pre>
      </Card>
    </div>
  );
}
