"use client";

import { useState, useTransition } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { StatusBadge, type BadgeTone } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import {
  deleteSmsDraftAction,
  dryRunSmsAction,
  duplicateSmsDraftAction,
  previewSmsAction,
  retrySmsMessageAction,
  saveSmsDraftAction,
  sendSmsCampaignAction,
  updateSmsDraftAction,
  type SmsActionState,
} from "@/lib/admin/live-actions";
import type {
  AdminSmsCampaignRow,
  AdminSmsDryRun,
  AdminSmsMessageRow,
  AdminSmsOverview,
  AdminSmsPreview,
  AdminSmsSettings,
} from "@/lib/admin/types";

type Tab = "overview" | "compose" | "drafts" | "history" | "settings";

interface MerchantOption {
  merchant_id: string;
  business_name: string;
  merchant_code: string | null;
}

/** collection_alert is retired (2026-10-17, cost) but still appears on
 * historical rows, so it keeps a label. */
const PURPOSE_LABELS: Record<string, string> = {
  welcome: "Welcome",
  withdrawal_complete: "Withdrawal confirmed",
  announcement: "Announcement",
  collection_alert: "Payment alert (retired)",
};

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "compose", label: "Compose" },
  { id: "drafts", label: "Drafts" },
  { id: "history", label: "History" },
  { id: "settings", label: "Settings" },
];

/** 'sent' is the gateway accepting the message, not a handset receiving
 * it, so it reads as "Accepted" rather than "Delivered" — the difference
 * matters when a merchant says they never got it. */
function statusBadge(status: string): { label: string; tone: BadgeTone } {
  switch (status) {
    case "sent":
      return { label: "Accepted by gateway", tone: "positive" };
    case "pending":
      return { label: "Pending at provider", tone: "pending" };
    case "queued":
    case "sending":
      return { label: "Queued", tone: "neutral" };
    case "failed":
      return { label: "Failed", tone: "negative" };
    case "unknown":
      return { label: "Outcome unknown", tone: "pending" };
    case "skipped":
      return { label: "Skipped", tone: "neutral" };
    case "cancelled":
      return { label: "Cancelled", tone: "neutral" };
    default:
      return { label: status, tone: "neutral" };
  }
}

function Feedback({ state }: { state: SmsActionState | null }) {
  if (!state) return null;
  if (state.error) {
    return (
      <p className="mt-2 inline-flex items-start gap-1 text-sm text-error">
        <Icon name="error" className="text-[16px] shrink-0" />
        {state.error}
      </p>
    );
  }
  if (state.ok) {
    return (
      <p className="mt-2 inline-flex items-start gap-1 text-sm text-primary">
        <Icon name="check_circle" className="text-[16px] shrink-0" />
        {state.message}
      </p>
    );
  }
  return null;
}

export function SmsWorkspace({
  overview,
  settings,
  campaigns,
  messages,
  merchants,
}: {
  overview: AdminSmsOverview;
  settings: AdminSmsSettings | null;
  campaigns: AdminSmsCampaignRow[];
  messages: AdminSmsMessageRow[];
  merchants: MerchantOption[];
}) {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <>
      {!overview.enabled && (
        <Card>
          <div className="flex items-start gap-3">
            <Icon name="info" className="text-[20px] text-on-surface-variant shrink-0" />
            <div className="text-sm text-on-surface-variant">
              <p className="font-semibold text-on-background">SMS is switched off.</p>
              <p className="mt-1">
                Nothing is queued and nothing is sent while <code>OASIS_SMS_ENABLED</code> is false.
                Switching it on starts alerting on payments from that moment — it never sends for
                payments that already happened.
              </p>
            </div>
          </div>
        </Card>
      )}

      <div className="flex gap-1 border-b border-surface-container-highest overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? "border-primary-container text-on-background"
                : "border-transparent text-on-surface-variant hover:text-on-background"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab overview={overview} messages={messages} />}
      {tab === "compose" && <ComposeTab merchants={merchants} senderId={overview.sender_id} />}
      {tab === "drafts" && <DraftsTab campaigns={campaigns} merchants={merchants} />}
      {tab === "history" && <HistoryTab campaigns={campaigns} messages={messages} />}
      {tab === "settings" && <SettingsTab settings={settings} />}
    </>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-on-background">{value}</p>
      {hint && <p className="mt-1 text-xs text-on-surface-variant">{hint}</p>}
    </Card>
  );
}

function OverviewTab({
  overview,
  messages,
}: {
  overview: AdminSmsOverview;
  messages: AdminSmsMessageRow[];
}) {
  const counts = overview.counts ?? {};
  const oldest = overview.oldest_waiting_at;
  const ageMinutes = oldest
    ? Math.round((Date.now() - new Date(oldest).getTime()) / 60000)
    : null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <Stat label="Queued" value={String((counts.queued ?? 0) + (counts.sending ?? 0))} />
        <Stat
          label="Accepted"
          value={String(counts.sent ?? 0)}
          hint="Gateway accepted — not a handset receipt"
        />
        <Stat label="Pending" value={String(counts.pending ?? 0)} hint="Provider could not confirm" />
        <Stat label="Failed" value={String(counts.failed ?? 0)} />
        <Stat label="Skipped" value={String(counts.skipped ?? 0)} hint="Never offered to the provider" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Stat
          label="Queue age"
          value={ageMinutes === null ? "—" : `${ageMinutes} min`}
          hint={ageMinutes === null ? "Nothing waiting" : "Oldest message still waiting"}
        />
        <Stat
          label="Provider credits"
          value={overview.provider_credits === null ? "—" : overview.provider_credits.toLocaleString()}
          hint={overview.provider_credits === null ? "Not configured or unreachable" : undefined}
        />
        <Stat
          label="Sender ID"
          value={overview.sender_id ?? "Not set"}
          hint={overview.sender_id ? "Must be approved by the provider" : "Nothing can send without one"}
        />
      </div>

      {overview.recent_skips.length > 0 && (
        <Card padded={false}>
          <div className="p-5 pb-2">
            <h3 className="text-lg font-semibold text-on-background">Why merchants were skipped</h3>
            <p className="text-sm text-on-surface-variant">
              A skip is not a failure — nothing was offered to the provider, and here is why.
            </p>
          </div>
          <ul className="px-5 pb-5 space-y-1.5 text-sm text-on-surface-variant">
            {overview.recent_skips.map((s, i) => (
              <li key={i} className="flex justify-between gap-4">
                <span>{s.reason}</span>
                <span className="text-xs shrink-0">{formatDateTime(s.at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <MessagesTable messages={messages.slice(0, 50)} title="Recent messages" />
    </div>
  );
}

function ComposeTab({
  merchants,
  senderId,
}: {
  merchants: MerchantOption[];
  senderId: string | null;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [allMerchants, setAllMerchants] = useState(true);
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<AdminSmsPreview | null>(null);
  const [quote, setQuote] = useState<AdminSmsDryRun | null>(null);
  const [state, setState] = useState<SmsActionState | null>(null);
  const [pending, startTransition] = useTransition();

  const merchantIds = allMerchants ? null : selected;

  function runPreview() {
    startTransition(async () => {
      try {
        setPreview(await previewSmsAction({ body, merchantIds }));
        setState(null);
      } catch {
        setState({ error: "Could not work out who this would reach.", ok: false, message: null });
      }
    });
  }

  function runDryRun() {
    startTransition(async () => {
      try {
        setQuote(await dryRunSmsAction({ body, merchantIds }));
        setState(null);
      } catch (err) {
        setQuote(null);
        setState({
          error: err instanceof Error ? err.message : "The provider could not price this message.",
          ok: false,
          message: null,
        });
      }
    });
  }

  function save() {
    startTransition(async () => {
      setState(await saveSmsDraftAction({ title, body, merchantIds }));
    });
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card>
        <h3 className="text-lg font-semibold text-on-background">Write an announcement</h3>
        <p className="mt-1 text-sm text-on-surface-variant">
          Saving creates a draft. Nothing is sent until you open it in Drafts and press Send.
        </p>

        <label className="mt-4 block text-sm font-medium text-on-background">Title</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Scheduled maintenance"
          className="mt-1 w-full rounded-lg border border-outline-variant bg-surface px-3 py-2 text-sm text-on-surface"
        />

        <label className="mt-4 block text-sm font-medium text-on-background">Message</label>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={5}
          placeholder="Habari. Huduma itasimama kwa muda..."
          className="mt-1 w-full rounded-lg border border-outline-variant bg-surface px-3 py-2 text-sm text-on-surface"
        />
        <p className="mt-1 text-xs text-on-surface-variant">
          Plain Swahili keeps the message in the cheaper encoding. One emoji or curly quote drops the
          part size from 160 characters to 70.
        </p>

        <div className="mt-4 space-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input type="radio" checked={allMerchants} onChange={() => setAllMerchants(true)} />
            Every eligible merchant
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" checked={!allMerchants} onChange={() => setAllMerchants(false)} />
            Choose merchants
          </label>
        </div>

        {!allMerchants && (
          <div className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-outline-variant p-2 space-y-1">
            {merchants.map((m) => (
              <label key={m.merchant_id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(m.merchant_id)}
                  onChange={(e) =>
                    setSelected((prev) =>
                      e.target.checked
                        ? [...prev, m.merchant_id]
                        : prev.filter((id) => id !== m.merchant_id),
                    )
                  }
                />
                <span>{m.business_name}</span>
                <span className="text-xs text-on-surface-variant font-mono">{m.merchant_code}</span>
              </label>
            ))}
          </div>
        )}

        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={runPreview}
            disabled={!body || pending}
            className="px-4 py-2 rounded-lg border border-outline-variant text-sm font-medium disabled:opacity-60"
          >
            Preview
          </button>
          <button
            type="button"
            onClick={runDryRun}
            disabled={!body || pending || !senderId}
            title="Asks the provider for a real price. Sends nothing and charges nothing."
            className="px-4 py-2 rounded-lg border border-outline-variant text-sm font-medium disabled:opacity-60"
          >
            Check cost with provider
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!title || !body || pending || !senderId}
            className="px-4 py-2 rounded-lg bg-primary-container text-on-surface text-sm font-semibold disabled:opacity-60"
          >
            Save as draft
          </button>
        </div>
        {!senderId && (
          <p className="mt-2 text-sm text-error">
            No approved sender ID is configured, so nothing can be sent yet.
          </p>
        )}
        <Feedback state={state} />
      </Card>

      <Card>
        <h3 className="text-lg font-semibold text-on-background">Who this reaches</h3>
        {preview === null ? (
          <p className="mt-2 text-sm text-on-surface-variant">
            Press Preview to see the recipient count, who is excluded and what it is likely to cost.
          </p>
        ) : (
          <div className="mt-3 space-y-4 text-sm">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs uppercase text-on-surface-variant">Recipients</p>
                <p className="text-2xl font-semibold text-on-background">{preview.recipient_count}</p>
              </div>
              <div>
                <p className="text-xs uppercase text-on-surface-variant">Excluded</p>
                <p className="text-2xl font-semibold text-on-background">{preview.excluded_count}</p>
              </div>
            </div>
            <p className="text-on-surface-variant">
              {preview.characters} characters · {preview.encoding} · {preview.segments_per_message} part
              {preview.segments_per_message === 1 ? "" : "s"} per message
            </p>
            <p className="text-on-surface-variant">
              Estimated cost <span className="font-semibold text-on-background">
                {preview.estimated_credits} credits
              </span>{" "}
              — our own figure from the text, not a quote confirmed by the provider.
            </p>
            {quote && (
              <div className="rounded-lg border border-outline-variant p-3">
                <p className="font-medium text-on-background">Confirmed by the provider</p>
                <p className="mt-1 text-on-surface-variant">
                  {quote.segments_per_message} part
                  {quote.segments_per_message === 1 ? "" : "s"} ·{" "}
                  {quote.credits_per_message} credit
                  {quote.credits_per_message === 1 ? "" : "s"} per message ·{" "}
                  <span className="font-semibold text-on-background">
                    {quote.credits_total} credits
                  </span>{" "}
                  for {quote.recipient_count} recipients.
                </p>
                {quote.enough_credits === false && (
                  <p className="mt-1 font-medium text-error">
                    Not enough credits on the provider account to send this.
                  </p>
                )}
                <p className="mt-1 text-xs text-on-surface-variant">
                  Nothing was sent and nothing was charged to check this.
                </p>
              </div>
            )}
            {preview.excluded.length > 0 && (
              <div>
                <p className="font-medium text-on-background">Not included</p>
                <ul className="mt-1 space-y-1 text-on-surface-variant">
                  {preview.excluded.map((e) => (
                    <li key={e.merchant_id}>
                      {e.business_name} — {e.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

function DraftsTab({
  campaigns,
  merchants,
}: {
  campaigns: AdminSmsCampaignRow[];
  merchants: MerchantOption[];
}) {
  const drafts = campaigns.filter((c) => c.status === "draft");
  const [state, setState] = useState<SmsActionState | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draftBody, setDraftBody] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [pending, startTransition] = useTransition();

  if (drafts.length === 0) {
    return (
      <Card>
        <p className="text-sm text-on-surface-variant">
          No unsent drafts. Write one in Compose — it stays here until you send it.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Feedback state={state} />
      {drafts.map((draft) => (
        <Card key={draft.id}>
          {editing === draft.id ? (
            <>
              <input
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                className="w-full rounded-lg border border-outline-variant bg-surface px-3 py-2 text-sm"
              />
              <textarea
                value={draftBody}
                onChange={(e) => setDraftBody(e.target.value)}
                rows={4}
                className="mt-2 w-full rounded-lg border border-outline-variant bg-surface px-3 py-2 text-sm"
              />
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    startTransition(async () => {
                      setState(
                        await updateSmsDraftAction(draft.id, {
                          title: draftTitle,
                          body: draftBody,
                          merchantIds: null,
                        }),
                      );
                      setEditing(null);
                    })
                  }
                  className="px-3 py-1.5 rounded-lg bg-primary-container text-on-surface text-sm font-semibold"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(null)}
                  className="px-3 py-1.5 rounded-lg border border-outline-variant text-sm"
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="font-semibold text-on-background">{draft.title}</h3>
                  <p className="mt-1 text-sm text-on-surface-variant whitespace-pre-wrap">{draft.body}</p>
                  <p className="mt-2 text-xs text-on-surface-variant">
                    Saved {formatDateTime(draft.created_at)}
                  </p>
                </div>
                <StatusBadge label="Draft" tone="neutral" />
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {confirming === draft.id ? (
                  <>
                    <span className="text-sm text-on-surface-variant self-center">
                      Send this to every eligible merchant?
                    </span>
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() =>
                        startTransition(async () => {
                          setState(await sendSmsCampaignAction(draft.id));
                          setConfirming(null);
                        })
                      }
                      className="px-3 py-1.5 rounded-lg bg-error text-on-error text-sm font-semibold disabled:opacity-60"
                    >
                      {pending ? "Sending…" : "Confirm send"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirming(null)}
                      className="px-3 py-1.5 rounded-lg border border-outline-variant text-sm"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    {/* Asks first, and cannot be double-submitted: the
                        backend refuses a second send outright. */}
                    <button
                      type="button"
                      onClick={() => setConfirming(draft.id)}
                      className="px-3 py-1.5 rounded-lg bg-primary-container text-on-surface text-sm font-semibold"
                    >
                      Send
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditing(draft.id);
                        setDraftTitle(draft.title);
                        setDraftBody(draft.body);
                      }}
                      className="px-3 py-1.5 rounded-lg border border-outline-variant text-sm"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() =>
                        startTransition(async () => setState(await duplicateSmsDraftAction(draft.id)))
                      }
                      className="px-3 py-1.5 rounded-lg border border-outline-variant text-sm"
                    >
                      Duplicate
                    </button>
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() =>
                        startTransition(async () => setState(await deleteSmsDraftAction(draft.id)))
                      }
                      className="px-3 py-1.5 rounded-lg border border-outline-variant text-sm text-error"
                    >
                      Delete
                    </button>
                  </>
                )}
              </div>
            </>
          )}
        </Card>
      ))}
      <p className="text-xs text-on-surface-variant">
        {merchants.length} merchants on the platform. Who actually receives an announcement is worked
        out when you press Send, from merchant records — never from a list typed here.
      </p>
    </div>
  );
}

function HistoryTab({
  campaigns,
  messages,
}: {
  campaigns: AdminSmsCampaignRow[];
  messages: AdminSmsMessageRow[];
}) {
  const sent = campaigns.filter((c) => c.status !== "draft");

  return (
    <div className="space-y-6">
      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-lg font-semibold text-on-background">Announcements</h3>
        </div>
        {sent.length === 0 ? (
          <p className="px-5 pb-5 text-sm text-on-surface-variant">Nothing has been sent yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[760px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Title</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Recipients</th>
                  <th className={thClass}>Excluded</th>
                  <th className={thClass}>Credits (est.)</th>
                  <th className={thClass}>Sent</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {sent.map((c) => (
                  <tr key={c.id} className="border-t border-surface-container-highest">
                    <td className={`${tdClass} font-medium text-on-background`}>{c.title}</td>
                    <td className={tdClass}>
                      <StatusBadge label={c.status} tone={c.status === "sent" ? "positive" : "neutral"} />
                    </td>
                    <td className={tdClass}>{c.recipient_count}</td>
                    <td className={tdClass}>{c.excluded_count}</td>
                    <td className={tdClass}>{c.estimated_credits ?? "—"}</td>
                    <td className={`${tdClass} text-xs text-on-surface-variant`}>
                      {c.dispatched_at ? formatDateTime(c.dispatched_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <MessagesTable messages={messages} title="Every message" retryable />
    </div>
  );
}

function MessagesTable({
  messages,
  title,
  retryable = false,
}: {
  messages: AdminSmsMessageRow[];
  title: string;
  retryable?: boolean;
}) {
  const [state, setState] = useState<SmsActionState | null>(null);
  const [pending, startTransition] = useTransition();

  return (
    <Card padded={false}>
      <div className="p-5 pb-3">
        <h3 className="text-lg font-semibold text-on-background">{title}</h3>
        <Feedback state={state} />
      </div>
      {messages.length === 0 ? (
        <p className="px-5 pb-5 text-sm text-on-surface-variant">No messages yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[960px]">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className={thClass}>Merchant</th>
                <th className={thClass}>To</th>
                <th className={thClass}>Type</th>
                <th className={thClass}>Status</th>
                <th className={thClass}>Parts</th>
                <th className={thClass}>Created</th>
                {retryable && <th className={thClass} />}
              </tr>
            </thead>
            <tbody className="text-sm">
              {messages.map((m) => (
                <tr key={m.id} className="border-t border-surface-container-highest align-top">
                  <td className={`${tdClass} text-on-background`}>
                    {m.business_name ?? "—"}
                    <span className="block text-xs font-mono text-on-surface-variant">
                      {m.merchant_code}
                    </span>
                  </td>
                  <td className={`${tdClass} font-mono text-xs`}>{m.recipient_phone}</td>
                  <td className={`${tdClass} text-xs text-on-surface-variant`}>
                    {PURPOSE_LABELS[m.purpose] ?? m.purpose}
                  </td>
                  <td className={tdClass}>
                    <StatusBadge {...statusBadge(m.status)} />
                    {m.skipped_reason && (
                      <p className="mt-1 text-xs text-on-surface-variant max-w-[22rem]">
                        {m.skipped_reason}
                      </p>
                    )}
                    {m.last_error && (
                      <p className="mt-1 text-xs text-error max-w-[22rem]">{m.last_error}</p>
                    )}
                  </td>
                  <td className={tdClass}>{m.segments ?? "—"}</td>
                  <td className={`${tdClass} text-xs text-on-surface-variant`}>
                    {formatDateTime(m.created_at)}
                  </td>
                  {retryable && (
                    <td className={tdClass}>
                      {/* Only a failed message may be retried. Anything the
                          provider may already hold is not offered a button:
                          requeuing one of those is how a merchant gets the
                          same alert twice. */}
                      {m.status === "failed" && (
                        <button
                          type="button"
                          disabled={pending}
                          onClick={() =>
                            startTransition(async () => setState(await retrySmsMessageAction(m.id)))
                          }
                          className="px-2 py-1 rounded-md border border-outline-variant text-xs"
                        >
                          Retry
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function SettingsTab({ settings }: { settings: AdminSmsSettings | null }) {
  if (!settings) {
    return (
      <Card>
        <p className="text-sm text-on-surface-variant">Settings could not be loaded.</p>
      </Card>
    );
  }

  const rows: { label: string; value: string; hint?: string }[] = [
    {
      label: "SMS dispatch",
      value: settings.enabled ? "On" : "Off",
      hint: "OASIS_SMS_ENABLED on the API service. Turning it off stops new sends and keeps all history.",
    },
    {
      label: "Welcome SMS",
      value: settings.welcome_enabled ? "On" : "Off",
      hint: "One per merchant, after their first approval. OASIS_SMS_WELCOME_ENABLED.",
    },
    {
      label: "Withdrawal SMS",
      value: settings.withdrawal_enabled ? "On" : "Off",
      hint: "One per payout, after the provider confirms it. OASIS_SMS_WITHDRAWAL_ENABLED.",
    },
    {
      label: "Cost per part",
      value: settings.credit_cost_tzs ? `TZS ${settings.credit_cost_tzs}` : "—",
      hint: "Used for estimates only. Never touches a fee or a ledger entry.",
    },
    {
      label: "Sender ID",
      value: settings.sender_id ?? "Not set",
      hint: "Must be approved by the provider, or every send is refused.",
    },
    {
      label: "API key",
      value: settings.api_key_configured ? "Configured" : "Not set",
      hint: "Server-side only. The key itself is never shown here or returned by any endpoint.",
    },
    {
      label: "Callback secret",
      value: settings.callback_secret_configured ? "Configured" : "Not set",
      hint: "Without it, provider callbacks are rejected rather than trusted.",
    },
    { label: "Dispatch interval", value: `${settings.dispatch_interval_seconds}s` },
    {
      label: "Send rate limit",
      value: `${settings.rate_limit_per_minute}/min`,
      hint: "Below the provider's 300/min account limit, leaving headroom for anything else sharing the account.",
    },
    { label: "Batch size", value: `${settings.batch_size} per sweep` },
    {
      label: "Announcement share",
      value: `${settings.announcement_batch_size} per sweep`,
      hint: "Capped so a bulk send cannot leave payment alerts waiting behind it.",
    },
    { label: "Attempts before giving up", value: String(settings.max_attempts) },
    {
      label: "Provider credits",
      value: settings.provider_credits === null ? "—" : settings.provider_credits.toLocaleString(),
    },
  ];

  return (
    <Card>
      <h3 className="text-lg font-semibold text-on-background">Configuration</h3>
      <p className="mt-1 text-sm text-on-surface-variant">
        These are environment variables on the API service, so changing one is a deployment rather
        than a form. No key or secret is shown here.
      </p>
      <dl className="mt-4 divide-y divide-surface-container-highest">
        {rows.map((row) => (
          <div key={row.label} className="py-3">
            <div className="flex justify-between gap-4">
              <dt className="text-sm text-on-surface-variant">{row.label}</dt>
              <dd className="text-sm font-medium text-on-background text-right">{row.value}</dd>
            </div>
            {row.hint && <p className="mt-1 text-xs text-on-surface-variant">{row.hint}</p>}
          </div>
        ))}
      </dl>
    </Card>
  );
}
