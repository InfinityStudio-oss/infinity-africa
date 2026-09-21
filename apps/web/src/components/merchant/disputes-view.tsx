"use client";

import { Fragment, useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { EmptyState } from "@/components/portal/empty-state";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { acceptRefund, getMyDispute, listMyDisputes, respondToDispute } from "@/lib/portal/api";
import type { Dispute, DisputeStatus, DisputeWithMessages } from "@/lib/portal/types";

const STATUS_TONE: Record<DisputeStatus, "positive" | "positive-solid" | "pending" | "negative" | "neutral" | "info"> = {
  SUBMITTED: "info",
  MERCHANT_NOTIFIED: "pending",
  UNDER_REVIEW: "pending",
  REFUND_REQUESTED: "pending",
  REFUNDED: "positive-solid",
  REJECTED: "negative",
  CLOSED: "neutral",
};

function DisputeDetail({ disputeId, onChanged }: { disputeId: string; onChanged: () => void }) {
  const [detail, setDetail] = useState<DisputeWithMessages | null>(null);
  const [response, setResponse] = useState("");
  const [refundAmount, setRefundAmount] = useState("");
  const [busy, setBusy] = useState(false);

  function reload() {
    getMyDispute(disputeId).then(setDetail);
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disputeId]);

  if (!detail) return <div className="p-5 text-sm text-on-surface-variant">Loading…</div>;

  async function handleRespond(event: React.FormEvent) {
    event.preventDefault();
    if (!response.trim()) return;
    setBusy(true);
    try {
      await respondToDispute(disputeId, response.trim());
      setResponse("");
      reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function handleAcceptRefund() {
    if (!refundAmount) return;
    setBusy(true);
    try {
      await acceptRefund(disputeId, refundAmount);
      reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-5 bg-surface-container-low space-y-4">
      <div>
        <h4 className="text-sm font-semibold text-on-background mb-2">Conversation</h4>
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {detail.messages.length === 0 ? (
            <p className="text-xs text-on-surface-variant">No messages yet.</p>
          ) : (
            detail.messages.map((message) => (
              <div key={message.id} className="text-xs bg-surface rounded-lg p-3 border border-surface-container-highest">
                <span className="font-semibold text-on-background capitalize">{message.sender_type}</span>
                <span className="text-on-surface-variant"> · {formatDateTime(message.created_at)}</span>
                <p className="mt-1 text-on-surface">{message.body}</p>
              </div>
            ))
          )}
        </div>
      </div>

      <form onSubmit={handleRespond} className="flex gap-2">
        <input
          value={response}
          onChange={(event) => setResponse(event.target.value)}
          placeholder="Type a response to this dispute…"
          className="flex-1 px-3.5 py-2.5 bg-surface border border-surface-container-highest rounded-lg text-sm focus:outline-none focus:border-primary"
        />
        <button
          type="submit"
          disabled={busy || !response.trim()}
          className="bg-primary-container text-on-primary text-sm font-medium px-4 rounded-lg hover:opacity-90 disabled:opacity-60"
        >
          Send
        </button>
      </form>

      {detail.transaction_id && detail.status !== "REFUNDED" && (
        <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-surface-container-highest">
          <span className="text-xs font-medium text-on-surface-variant">Accept refund:</span>
          <input
            value={refundAmount}
            onChange={(event) => setRefundAmount(event.target.value)}
            placeholder="Amount"
            className="w-32 px-3 py-2 bg-surface border border-surface-container-highest rounded-lg text-sm"
          />
          <button
            onClick={handleAcceptRefund}
            disabled={busy || !refundAmount}
            className="bg-white border border-primary text-primary text-xs font-semibold py-2 px-4 rounded-lg hover:bg-primary-container/10 disabled:opacity-60"
          >
            Accept &amp; Request Refund
          </button>
        </div>
      )}
    </div>
  );
}

export function DisputesView() {
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  function reload() {
    listMyDisputes().then((data) => {
      setDisputes(data);
      setLoading(false);
    });
  }

  useEffect(() => {
    reload();
  }, []);

  if (loading) return null;

  return (
    <div className="space-y-8">
      <PageHeader title="Disputes" description="Customer-reported issues on your transactions and InfinityPay's review of them." />

      {disputes.length === 0 ? (
        <Card>
          <EmptyState icon="gavel" heading="No disputes" body="No customer has reported an issue with your transactions." actionLabel="" />
        </Card>
      ) : (
        <Card padded={false}>
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[880px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold">
                  <th className={thClass}>Reference</th>
                  <th className={thClass}>Transaction</th>
                  <th className={thClass}>Customer Phone</th>
                  <th className={thClass}>Amount</th>
                  <th className={thClass}>Reason</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Submitted</th>
                  <th className={`${thClass} text-right`}>Action</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {disputes.map((dispute) => (
                  <Fragment key={dispute.id}>
                    <tr className="border-t border-surface-container-highest">
                      <td className={`${tdClass} font-mono text-xs`}>{dispute.id.slice(0, 8)}</td>
                      <td className={`${tdClass} font-mono text-xs`}>{dispute.transaction_reference ?? "—"}</td>
                      <td className={tdClass}>{dispute.customer_phone}</td>
                      <td className={tdClass}>{dispute.amount ? formatCurrency(dispute.amount, "TZS") : "—"}</td>
                      <td className={tdClass}>{dispute.reason_category.replace(/_/g, " ")}</td>
                      <td className={tdClass}>
                        <StatusBadge label={dispute.status.replace(/_/g, " ")} tone={STATUS_TONE[dispute.status]} />
                      </td>
                      <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(dispute.created_at)}</td>
                      <td className={`${tdClass} text-right`}>
                        <button
                          onClick={() => setExpanded(expanded === dispute.id ? null : dispute.id)}
                          className="inline-flex items-center gap-1 text-primary text-xs font-semibold hover:underline"
                        >
                          {expanded === dispute.id ? "Hide" : "View"}
                          <Icon name={expanded === dispute.id ? "expand_less" : "expand_more"} className="text-[16px]" />
                        </button>
                      </td>
                    </tr>
                    {expanded === dispute.id && (
                      <tr className="border-t border-surface-container-highest">
                        <td colSpan={8} className="p-0">
                          <DisputeDetail disputeId={dispute.id} onChanged={reload} />
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
    </div>
  );
}
