"use client";

import { Fragment, useActionState, useMemo, useState } from "react";
import { DISBURSEMENT_METHOD_LABELS } from "@infinity/shared";
import { useFormStatus } from "react-dom";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime, maskAccountIdentifier } from "@/lib/format";
import {
  approveWithdrawalAction,
  reconcilePendingWithdrawalsAction,
  refreshWithdrawalStatusAction,
  rejectWithdrawalAction,
  requestInfoWithdrawalAction,
  type WithdrawalActionState,
} from "@/lib/admin/live-actions";
import { adminWithdrawalBadge } from "@/lib/admin/status-tones";
import type { AdminWithdrawalRow } from "@/lib/admin/types";

/** Declared here, not in live-actions.ts: a "use server" module can only
 * export async functions, never a plain constant. */
const WITHDRAWAL_ACTION_IDLE: WithdrawalActionState = { error: null, ok: false, message: null };

const STATUS_FILTERS = [
  "All",
  "Pending Approval",
  "Info Requested",
  "Processing",
  "Successful",
  "Failed",
  "Rejected",
  "Needs Attention",
  "Needs Reconciliation",
  "Blocked",
  "Reversed",
] as const;

const STATUS_FILTER_MAP: Record<(typeof STATUS_FILTERS)[number], AdminWithdrawalRow["status"] | null> = {
  All: null,
  "Pending Approval": "PENDING_ADMIN_APPROVAL",
  "Info Requested": "INFO_REQUESTED",
  Processing: "PROCESSING",
  Successful: "SUCCESS",
  Failed: "FAILED",
  Rejected: "REJECTED",
  "Needs Attention": "NEEDS_ADMIN_ATTENTION",
  "Needs Reconciliation": "NEEDS_RECONCILIATION",
  Blocked: "BLOCKED_IP_WHITELIST",
  Reversed: "REVERSED",
};

const inputClass =
  "w-full px-2.5 py-1.5 bg-surface-container-low border border-surface-container-highest rounded-md text-xs focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary";

/** Must be a child of the <form>, per useFormStatus's own rule. */
function SubmitButton({ className, idleLabel, pendingLabel }: { className: string; idleLabel: string; pendingLabel: string }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} className={`${className} disabled:opacity-60`}>
      {pending ? pendingLabel : idleLabel}
    </button>
  );
}

/** Inline confirmation / error for a completed submit — the piece these
 * forms were missing, so a working action (or a failed one) looked like it
 * did nothing. */
function ActionFeedback({ state }: { state: WithdrawalActionState }) {
  if (state.error) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-error">
        <Icon name="error" className="text-[14px]" />
        {state.error}
      </span>
    );
  }
  if (state.ok) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-primary">
        <Icon name="check_circle" className="text-[14px]" />
        {state.message ?? "Done."}
      </span>
    );
  }
  return null;
}

function ReconcileForm() {
  const [state, formAction] = useActionState<WithdrawalActionState, FormData>(
    reconcilePendingWithdrawalsAction,
    WITHDRAWAL_ACTION_IDLE,
  );
  return (
    <form action={formAction} className="flex flex-wrap items-center gap-2">
      <SubmitButton
        className="px-3 py-1.5 rounded-lg border border-outline-variant text-on-surface-variant text-xs font-semibold hover:bg-surface-container-low"
        idleLabel="Reconcile Pending"
        pendingLabel="Reconciling…"
      />
      <ActionFeedback state={state} />
    </form>
  );
}

function ApproveForm({ id }: { id: string }) {
  const [state, formAction] = useActionState<WithdrawalActionState, FormData>(
    approveWithdrawalAction.bind(null, id),
    WITHDRAWAL_ACTION_IDLE,
  );
  return (
    <form action={formAction} className="inline-flex items-center gap-2">
      <SubmitButton
        className="px-3 py-1.5 rounded-lg bg-primary-container text-on-primary text-xs font-semibold hover:opacity-90"
        idleLabel="Approve"
        pendingLabel="Approving…"
      />
      <ActionFeedback state={state} />
    </form>
  );
}

function RejectForm({ id }: { id: string }) {
  const [state, formAction] = useActionState<WithdrawalActionState, FormData>(
    rejectWithdrawalAction.bind(null, id),
    WITHDRAWAL_ACTION_IDLE,
  );
  return (
    <form action={formAction} className="flex flex-wrap items-center gap-2">
      <input
        name="rejection_reason"
        required
        placeholder="Reason for rejecting this withdrawal (required)"
        className={`${inputClass} max-w-md`}
      />
      <SubmitButton
        className="px-3 py-1.5 rounded-lg bg-error text-white text-xs font-semibold shrink-0"
        idleLabel="Confirm Reject"
        pendingLabel="Rejecting…"
      />
      <ActionFeedback state={state} />
    </form>
  );
}

function RequestInfoForm({ id }: { id: string }) {
  const [state, formAction] = useActionState<WithdrawalActionState, FormData>(
    requestInfoWithdrawalAction.bind(null, id),
    WITHDRAWAL_ACTION_IDLE,
  );
  return (
    <form action={formAction} className="flex flex-wrap items-center gap-2">
      <input
        name="message"
        required
        placeholder="What do you need from the merchant?"
        className={`${inputClass} max-w-md`}
      />
      <input
        name="requested_documents"
        placeholder="Requested documents (comma-separated, optional)"
        className={`${inputClass} max-w-xs`}
      />
      <SubmitButton
        className="px-3 py-1.5 rounded-lg bg-primary-container text-on-primary text-xs font-semibold shrink-0"
        idleLabel="Send Request"
        pendingLabel="Sending…"
      />
      <ActionFeedback state={state} />
    </form>
  );
}

function RefreshStatusForm({ id }: { id: string }) {
  const [state, formAction] = useActionState<WithdrawalActionState, FormData>(
    refreshWithdrawalStatusAction.bind(null, id),
    WITHDRAWAL_ACTION_IDLE,
  );
  return (
    <form action={formAction} className="inline-flex flex-wrap items-center justify-end gap-2">
      <SubmitButton
        className="px-3 py-1.5 rounded-lg border border-outline-variant text-on-surface-variant text-xs font-semibold hover:bg-surface-container-low"
        idleLabel="Refresh Status"
        pendingLabel="Refreshing…"
      />
      <ActionFeedback state={state} />
    </form>
  );
}

export function WithdrawalsTable({ rows, queue }: { rows: AdminWithdrawalRow[]; queue: AdminWithdrawalRow[] }) {
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("All");
  const [expandedRejectId, setExpandedRejectId] = useState<string | null>(null);
  const [expandedInfoId, setExpandedInfoId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const target = STATUS_FILTER_MAP[statusFilter];
    if (!target) return rows;
    return rows.filter((row) => row.status === target);
  }, [rows, statusFilter]);

  return (
    <>
      {queue.length > 0 && (
        <Card className="border-amber-200" padded={false}>
          <div className="p-5 pb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Icon name="warning" className="text-amber-600" />
              <div>
                <h3 className="text-xl font-semibold text-on-background">Withdrawal Approval Queue</h3>
                <p className="text-sm text-on-surface-variant mt-0.5">
                  Every withdrawal request needs Super Admin approval before it&apos;s sent to the provider.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="bg-amber-100 text-amber-700 px-2.5 py-1 rounded-full text-xs font-semibold">
                {queue.length} pending
              </span>
              <ReconcileForm />
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[960px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Merchant</th>
                  <th className={thClass}>Destination</th>
                  <th className={thClass}>Method</th>
                  <th className={thClass}>Amount</th>
                  <th className={thClass}>Available Balance</th>
                  <th className={thClass}>Requested</th>
                  <th className={`${thClass} text-right`}>Approval</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {queue.map((request) => {
                  const insufficientBalance = Number(request.available_balance) < Number(request.total_reserved_amount ?? request.amount);
                  return (
                  <Fragment key={request.withdrawal_id}>
                    <tr className="border-t border-surface-container-highest">
                      <td className={tdClass}>
                        <div className="font-medium text-on-background">{request.merchant_name}</div>
                        {request.merchant_code && (
                          <div className="font-mono text-xs text-on-surface-variant">{request.merchant_code}</div>
                        )}
                      </td>
                      <td className={tdClass}>
                        <div>{request.destination}</div>
                        <div className="text-xs text-on-surface-variant font-mono">
                          {maskAccountIdentifier(request.destination_identifier)}
                        </div>
                      </td>
                      <td className={`${tdClass} text-on-surface-variant`}>{DISBURSEMENT_METHOD_LABELS[request.method]}</td>
                      <td className={`${tdClass} font-semibold text-on-background`}>{formatCurrency(request.amount, request.currency)}</td>
                      <td className={`${tdClass} ${insufficientBalance ? "text-red-600 font-semibold" : "text-on-surface-variant"}`}>
                        {formatCurrency(request.available_balance, request.currency)}
                      </td>
                      <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(request.created_at)}</td>
                      <td className={`${tdClass} align-top`}>
                        <div className="flex flex-wrap items-center justify-end gap-2">
                          <ApproveForm id={request.withdrawal_id} />
                          <button
                            type="button"
                            onClick={() => setExpandedRejectId((id) => (id === request.withdrawal_id ? null : request.withdrawal_id))}
                            className="px-3 py-1.5 rounded-lg border border-outline-variant text-on-surface-variant text-xs font-semibold hover:bg-surface-container-low"
                          >
                            Reject
                          </button>
                          <button
                            type="button"
                            onClick={() => setExpandedInfoId((id) => (id === request.withdrawal_id ? null : request.withdrawal_id))}
                            className="px-3 py-1.5 rounded-lg border border-outline-variant text-on-surface-variant text-xs font-semibold hover:bg-surface-container-low"
                          >
                            Request Info
                          </button>
                        </div>
                      </td>
                    </tr>
                    {expandedRejectId === request.withdrawal_id && (
                      <tr className="border-t border-surface-container-highest bg-surface-container-low">
                        <td className={tdClass} colSpan={7}>
                          <RejectForm id={request.withdrawal_id} />
                        </td>
                      </tr>
                    )}
                    {expandedInfoId === request.withdrawal_id && (
                      <tr className="border-t border-surface-container-highest bg-surface-container-low">
                        <td className={tdClass} colSpan={7}>
                          <RequestInfoForm id={request.withdrawal_id} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setStatusFilter(option)}
            className={
              statusFilter === option
                ? "px-3.5 py-2 rounded-full bg-primary-container/10 text-primary text-sm font-semibold"
                : "px-3.5 py-2 rounded-full bg-surface-container-low text-on-surface-variant text-sm font-semibold hover:bg-surface-container-highest"
            }
          >
            {option}
          </button>
        ))}
      </div>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Withdrawals</h3>
        </div>
        {filtered.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No withdrawals match this filter.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[920px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Date</th>
                  <th className={thClass}>Merchant</th>
                  <th className={thClass}>Destination</th>
                  <th className={thClass}>Method</th>
                  <th className={thClass}>Amount</th>
                  <th className={thClass}>Fees</th>
                  <th className={thClass}>Provider Ref</th>
                  <th className={thClass}>Status</th>
                  <th className={`${thClass} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {filtered.map((row) => {
                  const needsRefresh = row.status === "PROCESSING" || row.status === "NEEDS_RECONCILIATION";
                  return (
                    <tr key={row.withdrawal_id} className="border-t border-surface-container-highest">
                      <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(row.created_at)}</td>
                      <td className={tdClass}>
                        <div className="font-medium text-on-background">{row.merchant_name}</div>
                        {row.merchant_code && (
                          <div className="font-mono text-xs text-on-surface-variant">{row.merchant_code}</div>
                        )}
                      </td>
                      <td className={tdClass}>
                        <div>{row.destination}</div>
                        <div className="text-xs text-on-surface-variant font-mono">
                          {maskAccountIdentifier(row.destination_identifier)}
                        </div>
                      </td>
                      <td className={`${tdClass} text-on-surface-variant`}>{DISBURSEMENT_METHOD_LABELS[row.method]}</td>
                      <td className={`${tdClass} font-semibold text-on-background`}>{formatCurrency(row.amount, row.currency)}</td>
                      <td className={`${tdClass} text-on-surface-variant`}>{formatCurrency(row.total_charges, row.currency)}</td>
                      <td className={`${tdClass} text-on-surface-variant text-xs font-mono`}>{row.provider_reference ?? "—"}</td>
                      <td className={tdClass}>
                        <StatusBadge {...adminWithdrawalBadge(row.status, row.auto_approved)} />
                        {row.status === "REJECTED" && row.rejection_reason && (
                          <p className="text-xs text-on-surface-variant mt-1">{row.rejection_reason}</p>
                        )}
                        {row.auto_decision_reason && (
                          <p className="text-[11px] text-on-surface-variant mt-1">{row.auto_decision_reason}</p>
                        )}
                        {row.request_email_status === "failed" && (
                          <p className="text-[11px] text-amber-700 mt-1 flex items-center gap-1">
                            <Icon name="mail" className="text-[12px]" />
                            Request notification email failed
                          </p>
                        )}
                        {row.status === "SUCCESS" && row.success_email_status === "failed" && (
                          <p className="text-[11px] text-amber-700 mt-1 flex items-center gap-1">
                            <Icon name="mail" className="text-[12px]" />
                            Success email failed
                          </p>
                        )}
                      </td>
                      <td className={`${tdClass} text-right`}>
                        {needsRefresh && <RefreshStatusForm id={row.withdrawal_id} />}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
