import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  title: "Disbursements API",
};

const STATUSES: Array<[string, string]> = [
  ["PENDING_ADMIN_APPROVAL", "Every withdrawal starts here — no amount is ever auto-processed. Nothing is reserved, Selcom is never called."],
  ["INFO_REQUESTED", "A Super Admin asked for more information before deciding. You'll see this via a notification."],
  ["PROCESSING", "Approved. Balance reserved, payout sent to Selcom, awaiting confirmation."],
  ["SUCCESS", "Funds delivered. Terminal. (Sometimes called \"COMPLETED\" in prose — the API value is always SUCCESS.)"],
  ["FAILED", "Selcom declined the payout — the balance reservation was automatically reversed."],
  ["REJECTED", "A Super Admin declined the request outright. Nothing was ever reserved, so nothing to reverse."],
  ["NEEDS_ADMIN_ATTENTION", "An anomaly needs a human look — rare, not a normal outcome."],
  ["NEEDS_RECONCILIATION", "Selcom's response was ambiguous. Balance stays reserved pending manual resolution."],
  ["BLOCKED_IP_WHITELIST", "Selcom rejected the request because the backend's IP isn't whitelisted — an operator problem, not a payout failure. Balance stays reserved."],
  ["REVERSED", "A previously-SUCCESS payout was reversed after the fact by the provider."],
];

export default function DisbursementsApiPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">API Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Disbursements API</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-6 max-w-2xl">
        Withdraw from your InfinityPay balance programmatically — to a Selcom Pesa wallet, a mobile money number,
        or a bank account. Available balance is validated before anything is created, and every withdrawal is
        reviewed by an InfinityPay Super Admin before it reaches Selcom.
      </p>

      <div className="mb-10 max-w-2xl space-y-4">
        <Callout title="You don&apos;t need this to withdraw">
          Withdrawing is built into the dashboard — open <strong>Withdrawals</strong>, enter an amount and a
          destination, and confirm the emailed code. No API key, no integration, nothing to configure.
          This page is only for businesses that want to <em>automate</em> withdrawals from their own system,
          such as scheduled payouts. Most never need it.
        </Callout>
        <Callout title="Withdrawals vs. Disbursements">
          In the InfinityPay dashboard, businesses see this feature as <strong>Withdrawals</strong>. In the API, the
          technical endpoint may use <code className="font-mono text-xs">disbursements</code> for
          payment-provider compatibility. Internally, withdrawal approvals call the{" "}
          <strong>Selcom Business Disbursement API</strong> — that name only ever appears in backend/internal
          documentation, never in the dashboard or in customer-facing copy.
        </Callout>
        <Callout tone="warning" title="Every withdrawal needs Super Admin approval — no exceptions">
          Submitting a withdrawal never calls Selcom. It always comes back <code className="font-mono text-xs">PENDING_ADMIN_APPROVAL</code>,
          regardless of amount or method. Selcom is only ever contacted once an InfinityPay Super Admin approves the
          request in the dashboard.
        </Callout>
      </div>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Endpoints</h2>
        <div className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-5">
          <EndpointRow method="POST" path="/v1/merchant/withdrawals/quote" description="Calculate charges before submitting — no withdrawal is created, no funds are reserved." auth="dashboard" />
          <EndpointRow method="POST" path="/v1/merchant/withdrawals" description="Submit a withdrawal request. Always PENDING_ADMIN_APPROVAL." auth="dashboard, Idempotency-Key required" />
          <EndpointRow method="GET" path="/v1/merchant/withdrawals" description="List your own withdrawals." auth="dashboard" />
          <EndpointRow method="POST" path="/v1/disbursements/selcom-pesa" description="Payout to a Selcom Pesa wallet — direct API-key integration." auth="dashboard or API key, Idempotency-Key required" />
          <EndpointRow method="POST" path="/v1/disbursements/mobile-money" description="Payout to a mobile money number — direct API-key integration." auth="dashboard or API key, Idempotency-Key required" />
          <EndpointRow method="POST" path="/v1/disbursements/bank-account" description="Payout to a bank account (bank_name required) — direct API-key integration." auth="dashboard or API key, Idempotency-Key required" />
          <EndpointRow method="GET" path="/v1/disbursements" description="List disbursements (merchant_id required as a query param)." auth="dashboard or API key" />
          <EndpointRow method="GET" path="/v1/disbursements/{id}" description="Get a disbursement." auth="dashboard or API key" />
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          Approval itself (<code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">approve</code>/
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">reject</code>/
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">request-info</code>) is a
          Super Admin action, not something a business or API key ever calls — see the Super Admin console, not this API.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Phone number format</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Any phone-based destination (Selcom Pesa, mobile money) must be a Tanzanian number in the form{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">255XXXXXXXXX</code> —
          country code, no leading zero, <strong>no plus sign</strong>. InfinityPay normalizes
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">0747730270</code>,{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">747730270</code>, and{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">+255747730270</code> to
          the same canonical value automatically, but it&apos;s simplest to send it correctly already:
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="rounded-xl border border-green-600/30 bg-green-600/5 p-4">
            <p className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-2">Correct</p>
            <code className="font-mono text-sm">255747730270</code>
          </div>
          <div className="rounded-xl border border-error/30 bg-error/5 p-4">
            <p className="text-xs font-semibold text-error uppercase tracking-wide mb-2">Wrong</p>
            <code className="font-mono text-sm block">+255747730270</code>
            <code className="font-mono text-sm block">0747730270</code>
          </div>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Calculate charges</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Every business has its own negotiated fee — call this first to show the full breakdown before submitting.
          It never creates a withdrawal or touches your balance.
        </p>
        <div className="space-y-4">
          <CodeBlock language="json — POST /v1/merchant/withdrawals/quote">{`{
  "amount": "100000.00",
  "method": "MOBILE_MONEY",
  "destination_code": "MPESA",
  "destination_identifier": "255747730270"
}`}</CodeBlock>
          <CodeBlock language="json — 200 OK">{`{
  "success": true,
  "data": {
    "withdrawal_amount": "100000.00",
    "processor_charge": "300.00",
    "infinity_fee": "1500.00",
    "percentage_fee": "1000.00",
    "flat_fee": "500.00",
    "total_charges": "1800.00",
    "total_reserved_amount": "101800.00",
    "recipient_net_amount": "100000.00",
    "channel": "MOBILE_MONEY",
    "destination_code": "MPESA",
    "pricing_rule_id": "8f2c1a90-...",
    "pricing_rule_label": "Negotiated enterprise rate",
    "processor_fee_pass_through": true
  }
}`}</CodeBlock>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Submit a withdrawal</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Charges are recalculated and frozen server-side at submission time — never trust a client-side quote. Most
          requests come back <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">PENDING_ADMIN_APPROVAL</code>;
          a low-value request from an eligible, verified business may instead be processed automatically and come
          back already <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">PROCESSING</code> — check the
          response&apos;s <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">status</code> field
          rather than assuming one or the other.
        </p>
        <div className="space-y-4">
          <CodeBlock language="json — POST /v1/merchant/withdrawals">{`{
  "method": "MOBILE_MONEY",
  "amount": "100000.00",
  "destination_code": "MPESA",
  "destination_name": "Grace Mwakalinga",
  "destination_phone": "255747730270"
}`}</CodeBlock>
          <CodeBlock language="json — 202 Accepted">{`{
  "success": true,
  "data": {
    "id": "c9d8e7f6-...",
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "method": "MOBILE_MONEY",
    "amount": "100000.00",
    "currency": "TZS",
    "destination_name": "Grace Mwakalinga",
    "destination_identifier": "255747730270",
    "destination_code": "MPESA",
    "status": "PENDING_ADMIN_APPROVAL",
    "requires_approval": true,
    "total_charges": "1800.00",
    "total_reserved_amount": "101800.00",
    "recipient_net_amount": "100000.00",
    "provider_reference": null,
    "transaction_reference": null,
    "initiated_at": "2026-08-14T09:00:00Z",
    "completed_at": null,
    "created_at": "2026-08-14T09:00:00Z",
    "updated_at": "2026-08-14T09:00:00Z"
  }
}`}</CodeBlock>
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          For a bank account payout, use the <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">bank_name</code>/
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">bank_account_number</code>/
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">bank_account_name</code> fields
          instead of <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">destination_phone</code> — the
          account number is never phone-normalized.
        </p>
        <CodeBlock language="json — POST /v1/merchant/withdrawals (bank)">{`{
  "method": "BANK_ACCOUNT",
  "amount": "100000.00",
  "destination_code": "CRDB",
  "bank_name": "CRDB Bank",
  "bank_account_number": "0151234567890",
  "bank_account_name": "PAUL MASANJA"
}`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Insufficient balance</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Checked against the <strong>total reserved amount</strong> (withdrawal amount + all fees), not just the raw
          amount. If it&apos;s not enough, you get a <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">409</code> and
          nothing is created or reserved:
        </p>
        <CodeBlock language="json — 409 Conflict">{`{
  "success": false,
  "error": {
    "code": "insufficient_balance",
    "message": "Insufficient balance: available TZS 45,000, requested TZS 80,000 (amount + fees)",
    "details": null
  }
}`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Unverified account</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Withdrawals are only available to businesses who have completed onboarding verification. A business that
          isn&apos;t yet <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">active</code>/<code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">verified</code> gets
          the same <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">409</code> shape,
          before any balance check runs:
        </p>
        <CodeBlock language="json — 409 Conflict">{`{
  "success": false,
  "error": {
    "code": "withdrawal_restricted",
    "message": "Withdrawals require a verified, active account. Complete onboarding verification first.",
    "details": null
  }
}`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Status lifecycle</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border border-outline-variant/40 rounded-xl overflow-hidden">
            <thead className="bg-surface-container-low">
              <tr>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Status</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Meaning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {STATUSES.map(([status, meaning]) => (
                <tr key={status}>
                  <td className="px-4 py-2.5 font-mono text-xs text-on-surface whitespace-nowrap">{status}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant">{meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Super Admin approval</h2>
        <Callout title="Most withdrawals are held for manual review">
          A withdrawal typically comes back <code className="font-mono text-xs">PENDING_ADMIN_APPROVAL</code> with{" "}
          <code className="font-mono text-xs">requires_approval: true</code> and is <em>not</em> sent to Selcom until
          an InfinityPay Super Admin approves it in the dashboard. If withdrawal automation is enabled and this
          request is eligible (a verified business, within the configured per-transaction/daily automation limits,
          no open high-risk fraud alert), it&apos;s processed immediately instead and comes back{" "}
          <code className="font-mono text-xs">PROCESSING</code> with{" "}
          <code className="font-mono text-xs">auto_approved: true</code> — never assume which one you&apos;ll get.
          Poll <code className="font-mono text-xs">GET .../dashboard/withdrawals</code> or listen for{" "}
          <code className="font-mono text-xs">disbursement.success</code>/<code className="font-mono text-xs">disbursement.failed</code> to
          know the outcome either way.
        </Callout>
      </section>

      <DocsPager currentHref="/developers/disbursements" />
    </div>
  );
}
