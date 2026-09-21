"use client";

import { useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { EmptyState } from "@/components/portal/empty-state";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge, type BadgeTone } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import { listMyDocumentRequests, listMyRiskAlerts, submitDocumentRequestFile } from "@/lib/portal/api";
import type { DocumentRequest, FraudAlert, FraudRiskLevel } from "@/lib/portal/types";

const RISK_TONE: Record<FraudRiskLevel, BadgeTone> = {
  LOW: "neutral",
  MEDIUM: "pending",
  HIGH: "negative",
  CRITICAL: "negative",
};

const ALERT_STATUS_LABEL: Record<string, string> = {
  OPEN: "Under Review",
  UNDER_REVIEW: "Under Review",
  DOCUMENTS_REQUESTED: "Documents Requested",
  CLEARED: "Cleared",
  ESCALATED: "Escalated",
  CLOSED: "Closed",
};

const DOCUMENT_LABELS = [
  "receipt",
  "proof_of_delivery",
  "customer_agreement",
  "invoice",
  "product_service_evidence",
  "conversation_screenshot",
  "other",
];

function DocumentUploadForm({
  request,
  onUploaded,
}: {
  request: DocumentRequest;
  onUploaded: (updated: DocumentRequest) => void;
}) {
  const [label, setLabel] = useState(request.requested_documents[0] ?? DOCUMENT_LABELS[0]);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await submitDocumentRequestFile(request.id, label, file);
      onUploaded(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-2.5 items-start sm:items-center mt-3">
      <select
        value={label}
        onChange={(event) => setLabel(event.target.value)}
        className="px-3 py-2 bg-surface-container-low border border-surface-container-highest rounded-lg text-xs"
      >
        {DOCUMENT_LABELS.map((option) => (
          <option key={option} value={option}>
            {option.replace(/_/g, " ")}
          </option>
        ))}
      </select>
      <input
        type="file"
        accept=".pdf,.jpg,.jpeg,.png"
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        className="text-xs"
      />
      <button
        type="submit"
        disabled={submitting || !file}
        className="bg-primary-container text-on-primary text-xs font-semibold py-2 px-4 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
      >
        {submitting ? "Uploading…" : "Upload"}
      </button>
      {error && <span className="text-xs text-error">{error}</span>}
    </form>
  );
}

export function RiskMonitoringView() {
  const [alerts, setAlerts] = useState<FraudAlert[]>([]);
  const [requests, setRequests] = useState<DocumentRequest[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([listMyRiskAlerts(), listMyDocumentRequests()]).then(([alertsData, requestsData]) => {
      setAlerts(alertsData);
      setRequests(requestsData);
      setLoading(false);
    });
  }, []);

  if (loading) return null;

  const openAlerts = alerts.filter((a) => !["CLEARED", "CLOSED"].includes(a.status));

  return (
    <div className="space-y-8">
      <PageHeader
        title="Risk Monitoring"
        description="Transactions flagged for review and any supporting documents InfinityPay has requested."
      />

      {openAlerts.length > 0 && (
        <Card>
          <div className="flex items-start gap-3 p-1">
            <Icon name="gpp_maybe" className="text-error text-[22px] shrink-0" />
            <div>
              <h3 className="font-semibold text-on-background mb-1">Transaction under review</h3>
              <p className="text-sm text-on-surface-variant">
                Please submit any supporting documents requested by InfinityPay below. Withdrawals may be temporarily
                restricted while a high-risk transaction is under review.
              </p>
            </div>
          </div>
        </Card>
      )}

      {alerts.length === 0 ? (
        <Card>
          <EmptyState
            icon="verified_user"
            heading="No risk alerts"
            body="Nothing has been flagged for review on your account."
            actionLabel=""
          />
        </Card>
      ) : (
        <Card padded={false}>
          <div className="p-5 pb-3">
            <h3 className="text-2xl font-semibold text-on-background">Alerts</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[820px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Risk</th>
                  <th className={thClass}>Reason</th>
                  <th className={thClass}>Required Action</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Created</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {alerts.map((alert) => (
                  <tr key={alert.id} className="border-t border-surface-container-highest align-top">
                    <td className={tdClass}>
                      <StatusBadge label={alert.risk_level} tone={RISK_TONE[alert.risk_level]} dot />
                    </td>
                    <td className={`${tdClass} max-w-[320px]`}>{alert.reason}</td>
                    <td className={`${tdClass} text-on-surface-variant`}>
                      {alert.status === "DOCUMENTS_REQUESTED"
                        ? "Submit supporting documents below"
                        : "Under review — no action needed yet"}
                    </td>
                    <td className={tdClass}>
                      <StatusBadge label={ALERT_STATUS_LABEL[alert.status] ?? alert.status} tone="neutral" />
                    </td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(alert.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">Document Requests</h3>
        </div>
        {requests.length === 0 ? (
          <div className="px-5 pb-6">
            <EmptyState
              icon="folder_shared"
              heading="No document requests"
              body="InfinityPay hasn't asked for supporting documents on any transaction."
              actionLabel=""
            />
          </div>
        ) : (
          <div className="divide-y divide-surface-container-highest">
            {requests.map((request) => (
              <div key={request.id} className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div>
                    <p className="text-sm font-semibold text-on-background">{request.requested_documents.join(", ")}</p>
                    <p className="text-xs text-on-surface-variant mt-0.5">{request.reason}</p>
                  </div>
                  <StatusBadge
                    label={request.status}
                    tone={request.status === "APPROVED" ? "positive" : request.status === "REJECTED" ? "negative" : "pending"}
                  />
                </div>
                {request.due_date && <p className="text-xs text-on-surface-variant">Due {formatDateTime(request.due_date)}</p>}
                {request.files.length > 0 && (
                  <ul className="mt-2 text-xs text-on-surface-variant list-disc pl-4">
                    {request.files.map((file) => (
                      <li key={file.id}>{file.original_filename}</li>
                    ))}
                  </ul>
                )}
                {request.status === "PENDING" && (
                  <DocumentUploadForm
                    request={request}
                    onUploaded={(updated) => setRequests((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
