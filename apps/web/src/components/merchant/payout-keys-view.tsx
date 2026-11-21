"use client";

import { useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { CopyButton } from "@/components/portal/copy-button";
import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { createApiKey, getPayoutWallet, listApiKeys, revokeApiKey, rotateApiKey } from "@/lib/portal/api";
import type { ApiKey, PayoutWallet } from "@/lib/portal/types";

/**
 * Payout keys, kept on their own tab rather than mixed into API Keys.
 *
 * A collections key can take money in. A payout key can send money out,
 * with no person approving each call. Listing them in one table styled
 * identically is how a merchant comes to treat a payout key with the same
 * care as a publishable-adjacent one, and the blast radius is not the
 * same. The separation is the explanation.
 *
 * The honest framing of the risk belongs on this screen too: the payout
 * wallet balance is the ceiling on what a leaked key can cost, because a
 * key cannot top up the wallet it spends from. That is worth saying where
 * the key is issued, not only in the docs.
 */

const PAYOUT_SCOPES = ["payouts:create", "payouts:read"] as const;

export function PayoutKeysView() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [wallet, setWallet] = useState<PayoutWallet | null>(null);
  const [noAccess, setNoAccess] = useState(false);
  const [loading, setLoading] = useState(true);

  const [creating, setCreating] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [environment, setEnvironment] = useState<"sandbox" | "live">("sandbox");
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<{ key: ApiKey; plaintext: string } | null>(null);

  async function load() {
    setLoading(true);
    const [allKeys, walletResult] = await Promise.all([listApiKeys(), getPayoutWallet()]);
    setKeys(allKeys.filter((key) => key.key_type === "payout"));
    setNoAccess(walletResult.noAccess);
    setWallet(walletResult.data);
    setLoading(false);
  }

  useEffect(() => {
    void load();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setCreating(true);
    try {
      const result = await createApiKey({
        name,
        environment,
        scopes: [...PAYOUT_SCOPES],
        key_type: "payout",
      });
      setIssued({ key: result.key, plaintext: result.plaintext_key });
      setName("");
      setFormOpen(false);
      await load();
    } catch (caught) {
      // The backend's message, because the likely one is specific and
      // actionable: payouts are not enabled for this environment yet.
      setError(caught instanceof Error ? caught.message : "Could not create the key.");
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return <div className="text-sm on-gradient-muted">Loading…</div>;
  }

  if (noAccess) {
    return (
      <Card>
        <div className="text-center py-6">
          <Icon name="send_money" className="text-[40px] text-on-surface-variant" />
          <h2 className="mt-3 text-lg font-semibold">Payout keys need the Disbursement API</h2>
          <p className="mt-2 text-sm text-on-surface-variant max-w-xl mx-auto">
            Payout keys let your server send money out automatically, drawing on a payout wallet you
            fund in advance. Access is granted per account and per environment — contact InfinityPay
            support to start in the sandbox.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-col gap-3">
          <div className="flex items-start gap-3">
            <Icon name="info" className="text-[20px] text-on-surface-variant shrink-0 mt-0.5" />
            <div className="text-sm text-on-surface-variant">
              <p>
                A payout key can send money out without anyone approving each request. It can only
                spend what is already in your payout wallet, and it{" "}
                <span className="font-semibold">cannot</span> top that wallet up — funding is a
                dashboard action behind two-factor authentication. That balance is your ceiling if a
                key ever leaks.
              </p>
              <p className="mt-2">
                A payout key also cannot reach your Collections balance or request a withdrawal.
                Those stay with your dashboard.
              </p>
            </div>
          </div>
          {wallet && (
            <p className="text-sm">
              <span className="text-on-surface-variant">Payout wallet ({wallet.environment}):</span>{" "}
              <span className="font-semibold">
                {wallet.available} {wallet.currency}
              </span>{" "}
              <span className="text-on-surface-variant">available,</span>{" "}
              <span className="font-semibold">
                {wallet.reserved} {wallet.currency}
              </span>{" "}
              <span className="text-on-surface-variant">reserved</span>
            </p>
          )}
        </div>
      </Card>

      {issued && (
        <Card>
          <div className="space-y-2">
            <h3 className="text-base font-semibold">Copy your payout key now</h3>
            <p className="text-sm text-on-surface-variant">
              This is the only time it is shown. We store a hash, so it cannot be looked up later —
              if you lose it, rotate the key.
            </p>
            <code
              id="copyable-payout-key"
              className="block px-3 py-2 rounded-lg bg-surface-container-highest font-mono text-xs break-all"
            >
              {issued.plaintext}
            </code>
            {/* There was no copy button here at all - the key was shown
                once, and the only way to take it was to select it by
                hand. "I have copied it" then dismissed the one copy that
                will ever exist. */}
            <div className="flex items-center gap-3 pt-1">
              <CopyButton value={issued.plaintext} describes="payout key" />
              <button
                type="button"
                onClick={() => setIssued(null)}
                className="text-sm font-medium text-primary hover:underline"
              >
                I have copied it
              </button>
            </div>
          </div>
        </Card>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Payout keys</h2>
        <button
          type="button"
          onClick={() => setFormOpen((open) => !open)}
          className="px-3 py-2 rounded-lg bg-primary text-on-primary text-sm font-semibold inline-flex items-center gap-1.5"
        >
          <Icon name="add" className="text-[18px]" />
          New payout key
        </button>
      </div>

      {formOpen && (
        <Card>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="payout-key-name" className="block text-sm font-medium mb-1">
                Name
              </label>
              <input
                id="payout-key-name"
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Billing server"
                className="w-full max-w-sm px-3 py-2 rounded-lg border border-surface-container-highest bg-surface text-sm"
              />
            </div>
            <div>
              <label htmlFor="payout-key-env" className="block text-sm font-medium mb-1">
                Environment
              </label>
              <select
                id="payout-key-env"
                value={environment}
                onChange={(event) => setEnvironment(event.target.value as "sandbox" | "live")}
                className="w-full max-w-sm px-3 py-2 rounded-lg border border-surface-container-highest bg-surface text-sm"
              >
                <option value="sandbox">Sandbox — simulated, no real money</option>
                <option value="live">Live</option>
              </select>
            </div>
            <p className="text-xs text-on-surface-variant">
              Scopes are fixed for this key type: <code>payouts:create</code> and{" "}
              <code>payouts:read</code>. A payout key cannot hold any other scope.
            </p>
            {error && <p className="text-sm text-red-700 font-medium">{error}</p>}
            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={creating}
                className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-semibold disabled:opacity-50"
              >
                {creating ? "Creating…" : "Create key"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setFormOpen(false);
                  setError(null);
                }}
                className="px-4 py-2 rounded-lg border border-surface-container-highest text-sm font-medium"
              >
                Cancel
              </button>
            </div>
          </form>
        </Card>
      )}

      <Card padded={false}>
        {keys.length === 0 ? (
          <div className="p-8 text-center text-sm text-on-surface-variant">
            No payout keys yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className={thClass}>Name</th>
                  <th className={thClass}>Environment</th>
                  <th className={thClass}>Key</th>
                  <th className={thClass}>Last used</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass} />
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.id} className="border-t border-surface-container-highest/60">
                    <td className={tdClass}>{key.name}</td>
                    <td className={tdClass}>
                      <StatusBadge
                        tone={key.environment === "live" ? "info" : "neutral"}
                        label={key.environment}
                      />
                    </td>
                    <td className={tdClass}>
                      <span className="font-mono text-xs">
                        {key.key_prefix}…{key.key_last4 ?? ""}
                      </span>
                    </td>
                    <td className={tdClass}>
                      {key.last_used_at ? formatDateTime(key.last_used_at) : "Never"}
                    </td>
                    <td className={tdClass}>
                      <StatusBadge
                        tone={key.status === "active" ? "positive" : "neutral"}
                        label={key.status}
                        strikethrough={key.status === "revoked"}
                      />
                    </td>
                    <td className={tdClass}>
                      {key.status === "active" && (
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={async () => {
                              const result = await rotateApiKey(key.id);
                              setIssued({ key: result.key, plaintext: result.plaintext_key });
                              await load();
                            }}
                            className="text-sm font-medium text-primary"
                          >
                            Rotate
                          </button>
                          <button
                            type="button"
                            onClick={async () => {
                              await revokeApiKey(key.id);
                              await load();
                            }}
                            className="text-sm font-medium text-red-700"
                          >
                            Revoke
                          </button>
                        </div>
                      )}
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
