"use client";

import { useState } from "react";

import { Card } from "@/components/portal/card";
import { EmptyState } from "@/components/portal/empty-state";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { SegmentedControl } from "@/components/portal/segmented-control";
import { generateReport } from "@/lib/portal/api";
import type { GeneratedReport, ReportFormat, ReportType } from "@/lib/portal/types";

const REPORT_TYPES: { value: ReportType; label: string }[] = [
  { value: "TRANSACTIONS_SUMMARY", label: "Transactions Summary" },
  { value: "WITHDRAWALS_SUMMARY", label: "Withdrawals Summary" },
  { value: "FEES_SUMMARY", label: "Fees Summary" },
  { value: "CUSTOMER_STATEMENT", label: "Customer Statement" },
];

const inputClass =
  "w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm";

/** Defaults to the current month so the form is submittable without the
 * merchant having to fill in two dates before they can try anything. */
function defaultRange(): { from: string; to: string } {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(now) };
}

export default function ReportsPage() {
  const initial = defaultRange();
  const [reportType, setReportType] = useState<ReportType>("TRANSACTIONS_SUMMARY");
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const [format, setFormat] = useState<ReportFormat>("PDF");
  const [extraRecipients, setExtraRecipients] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<GeneratedReport[]>([]);

  async function handleGenerate(event: React.FormEvent) {
    event.preventDefault();
    setGenerating(true);
    setError(null);
    try {
      const report = await generateReport({
        report_type: reportType,
        start_date: from,
        end_date: to,
        format,
        // Split on commas/whitespace so a merchant can paste a short list.
        // The backend validates each address and always adds the account
        // email itself, so an empty box is the normal case.
        recipients: extraRecipients
          .split(/[,\s]+/)
          .map((value) => value.trim())
          .filter(Boolean),
      });
      setSent((previous) => [report, ...previous]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't generate the report. Please try again.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Reports"
        description="Generate reports for accounting, reconciliation, and tax filing. Each report is emailed to you with the file attached."
      />

      <Card>
        <h3 className="text-2xl font-semibold text-on-background mb-5">Generate a Report</h3>
        <form onSubmit={handleGenerate} className="space-y-5">
          <div>
            <label htmlFor="report-type" className="block text-sm font-medium text-on-surface-variant mb-1.5">
              Report Type
            </label>
            <select
              id="report-type"
              value={reportType}
              onChange={(event) => setReportType(event.target.value as ReportType)}
              className={inputClass}
            >
              {REPORT_TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </div>
          <div className="grid sm:grid-cols-2 gap-5">
            <div>
              <label htmlFor="report-from" className="block text-sm font-medium text-on-surface-variant mb-1.5">
                From
              </label>
              <input
                id="report-from"
                className={inputClass}
                type="date"
                required
                value={from}
                onChange={(event) => setFrom(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="report-to" className="block text-sm font-medium text-on-surface-variant mb-1.5">
                To
              </label>
              <input
                id="report-to"
                className={inputClass}
                type="date"
                required
                value={to}
                onChange={(event) => setTo(event.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-2">Format</label>
            <SegmentedControl
              options={[
                { value: "PDF" as const, label: "PDF" },
                { value: "CSV" as const, label: "CSV" },
              ]}
              value={format}
              onChange={setFormat}
            />
          </div>
          <div>
            <label htmlFor="report-recipients" className="block text-sm font-medium text-on-surface-variant mb-1.5">
              Also email to (optional)
            </label>
            <input
              id="report-recipients"
              className={inputClass}
              type="text"
              placeholder="accountant@example.com, auditor@example.com"
              value={extraRecipients}
              onChange={(event) => setExtraRecipients(event.target.value)}
            />
            <p className="text-xs text-on-surface-variant mt-1.5">
              Always sent to your account email as well.
            </p>
          </div>

          {error && (
            <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error" role="alert">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={generating}
            className="bg-primary-container text-on-primary text-sm font-medium py-3 px-6 rounded-lg hover:opacity-90 transition-opacity flex items-center justify-center gap-2 disabled:opacity-60"
          >
            <Icon name="bar_chart" className="text-[20px]" />
            {generating ? "Generating and sending…" : "Generate Report"}
          </button>
        </form>
      </Card>

      <Card>
        {sent.length === 0 ? (
          <EmptyState
            icon="description"
            heading="No reports generated yet"
            body="Reports you generate are emailed to you with the file attached, as PDF or CSV."
            actionLabel="Generate Your First Report"
            onAction={() => document.querySelector("form")?.requestSubmit()}
          />
        ) : (
          <ul className="divide-y divide-surface-container-highest">
            {sent.map((report, index) => (
              <li key={`${report.filename}-${index}`} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-start gap-3">
                  <Icon name="task_alt" className="text-primary mt-0.5" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-on-background">
                      {report.title} — {report.start_date} to {report.end_date}
                    </p>
                    <p className="text-sm text-on-surface-variant">
                      {report.row_count} row{report.row_count === 1 ? "" : "s"}, sent as {report.format} to{" "}
                      {report.emailed_to.join(", ")}
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
