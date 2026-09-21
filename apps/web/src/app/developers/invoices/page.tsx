import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  title: "Invoices API",
};

export default function InvoicesApiPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">API Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Invoices API</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Itemized invoices with an auto-generated invoice number and a built-in &quot;Pay Now&quot; link, so a customer
        can settle by mobile money the moment they receive it.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Endpoints</h2>
        <div className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-5">
          <EndpointRow method="POST" path="/v1/invoices" description="Create an itemized invoice. invoice_number is generated for you." auth="dashboard or API key" />
          <EndpointRow method="GET" path="/v1/invoices" description="List invoices (merchant_id required as a query param)." auth="dashboard or API key" />
          <EndpointRow method="GET" path="/v1/invoices/{invoice_id}" description="Get an invoice." auth="dashboard or API key" />
          <EndpointRow method="PATCH" path="/v1/invoices/{invoice_id}" description="Edit an invoice — only while DRAFT." auth="dashboard or API key" />
          <EndpointRow method="POST" path="/v1/invoices/{invoice_id}/send" description="DRAFT → SENT." auth="dashboard or API key" />
          <EndpointRow method="POST" path="/v1/invoices/{invoice_id}/payment-link" description="Generate (or reuse) a Pay Now link for the remaining balance." auth="dashboard or API key" />
          <EndpointRow method="PATCH" path="/v1/invoices/{invoice_id}/cancel" description="Cancel an invoice. Idempotent; rejects an already-PAID invoice." auth="dashboard or API key" />
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Create an invoice</h2>
        <div className="space-y-4">
          <CodeBlock language="json — POST /v1/invoices">{`{
  "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
  "customer_name": "Juma Traders Ltd",
  "customer_phone": "+255712445310",
  "due_date": "2026-09-01",
  "notes": "Payment due within 14 days of receipt",
  "items": [
    { "description": "Wholesale delivery — 50kg bags", "quantity": "4", "unit_price": "70000.00" },
    { "description": "Transport fee", "quantity": "1", "unit_price": "40000.00" }
  ]
}`}</CodeBlock>
          <CodeBlock language="json — 201 Created">{`{
  "success": true,
  "data": {
    "id": "e5f6a7b8-...",
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "invoice_number": "INV-20260814-9F3A1C2B",
    "customer_name": "Juma Traders Ltd",
    "customer_phone": "+255712445310",
    "customer_email": null,
    "due_date": "2026-09-01",
    "currency": "TZS",
    "subtotal": "320000.00",
    "tax_amount": "0.00",
    "discount_amount": "0.00",
    "total_amount": "320000.00",
    "amount_paid": "0.00",
    "status": "DRAFT",
    "payment_link_id": null,
    "notes": "Payment due within 14 days of receipt",
    "items": [
      { "id": "...", "description": "Wholesale delivery — 50kg bags", "quantity": "4.00", "unit_price": "70000.00", "line_total": "280000.00", "sort_order": 0 },
      { "id": "...", "description": "Transport fee", "quantity": "1.00", "unit_price": "40000.00", "line_total": "40000.00", "sort_order": 1 }
    ],
    "created_at": "2026-08-14T09:00:00Z",
    "updated_at": "2026-08-14T09:00:00Z"
  }
}`}</CodeBlock>
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          Every invoice starts <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">DRAFT</code>.
          Nothing is sent to the customer, and it can&apos;t be paid, until you call{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">.../send</code>.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Getting an invoice paid</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Invoices don&apos;t have their own checkout page — they reuse the Payment Links product.{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">POST .../payment-link</code> generates
          an ordinary payment link for the invoice&apos;s remaining balance (
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">total_amount - amount_paid</code>)
          and returns it in the same shape as the{" "}
          <a href="/developers/payment-links" className="text-primary font-semibold hover:underline">
            Payment Links API
          </a>
          . Only a <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">SENT</code>,{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">PARTIALLY_PAID</code>, or{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">OVERDUE</code> invoice can
          generate one.
        </p>
        <CodeBlock language="json — POST /v1/invoices/{invoice_id}/payment-link">{`{
  "success": true,
  "data": {
    "id": "a1b2c3d4-...",
    "amount": "320000.00",
    "status": "ACTIVE",
    "public_slug": "PLK-4M18RT",
    "public_url": "https://pay.infinitypay.me/link/PLK-4M18RT",
    "...": "same PaymentLinkResponse shape"
  }
}`}</CodeBlock>
        <Callout title="Invoice status follows the payment automatically">
          When that generated link is paid, InfinityPay credits <code className="font-mono text-xs">amount_paid</code> and
          moves the invoice to <code className="font-mono text-xs">PARTIALLY_PAID</code> or{" "}
          <code className="font-mono text-xs">PAID</code> on its own — you don&apos;t reconcile this by hand. Listen for
          the <code className="font-mono text-xs">invoice.paid</code> webhook to know the moment it happens.
        </Callout>
      </section>

      <section>
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
              {[
                ["DRAFT", "Just created. Editable. Not payable yet."],
                ["SENT", "Sent to the customer. Now payable via a generated Pay Now link."],
                ["PARTIALLY_PAID", "Some, but not all, of total_amount has been collected."],
                ["PAID", "Fully collected. Terminal."],
                ["OVERDUE", "Past due_date and not yet fully paid."],
                ["CANCELLED", "Cancelled by the merchant. Terminal."],
              ].map(([status, meaning]) => (
                <tr key={status}>
                  <td className="px-4 py-2.5 font-mono text-xs text-on-surface">{status}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant">{meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <DocsPager currentHref="/developers/invoices" />
    </div>
  );
}
