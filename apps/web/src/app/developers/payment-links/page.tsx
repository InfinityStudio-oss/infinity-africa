import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  title: "Payment Links API",
};

export default function PaymentLinksApiPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">API Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Payment Links API</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Generate a secure, shareable checkout URL for a fixed amount — no website required on your end. Share it via
        SMS, WhatsApp, or email; the customer pays it on InfinityPay&apos;s own payment page, where they choose
        Mobile Money Push, Selcom Pesa, or Scan QR / TanQR themselves. This is the same underlying resource{" "}
        <a href="/developers/collections" className="text-primary font-semibold hover:underline">
          POST /v1/collections
        </a>{" "}
        (the Collections API&apos;s &quot;Infinity Payment Page&quot; flow) creates — use whichever endpoint shape
        fits your integration.
      </p>

      <Callout tone="warning" title="Selcom Hosted Checkout is not used">
        &quot;InfinityPay&apos;s payment page&quot; above means Infinity&apos;s own <code className="font-mono text-xs">/pay/…</code> page,
        not a redirect to Selcom&apos;s hosted checkout — that product is currently inactive platform-wide (see the{" "}
        <a href="/developers/go-live-checklist" className="text-primary font-semibold hover:underline">
          Go-Live Checklist
        </a>
        ). A payment link&apos;s <code className="font-mono text-xs">public_url</code> always points at Infinity&apos;s
        own page.
      </Callout>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Endpoints</h2>
        <div className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-5">
          <EndpointRow method="POST" path="/v1/payment-links" description="Create a payment link." auth="Idempotency-Key required" />
          <EndpointRow method="GET" path="/v1/payment-links/{link_id}" description="Get a payment link (reports EXPIRED once expires_at has passed)." auth="dashboard" />
          <EndpointRow method="PATCH" path="/v1/payment-links/{link_id}/cancel" description="Cancel a link. Idempotent; rejects an already-PAID link." auth="dashboard" />
          <EndpointRow method="GET" path="/public/payment-links/{public_slug}" description="Public checkout view — no auth. Always 200 for a slug that exists." auth="public" />
          <EndpointRow method="POST" path="/public/payment-links/{public_slug}/collect" description="Customer pays the link. 409 if not ACTIVE." auth="public, Idempotency-Key required" />
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Create a link</h2>
        <div className="space-y-4">
          <CodeBlock language="json — POST /v1/payment-links">{`{
  "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
  "amount": "25000.00",
  "currency": "TZS",
  "customer_name": "Grace Mwakalinga",
  "customer_phone": "+255754221908",
  "description": "Web design deposit",
  "expires_at": "2026-08-24T00:00:00Z"
}`}</CodeBlock>
          <CodeBlock language="json — 201 Created">{`{
  "success": true,
  "data": {
    "id": "a1b2c3d4-...",
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "amount": "25000.00",
    "currency": "TZS",
    "customer_name": "Grace Mwakalinga",
    "customer_phone": "+255754221908",
    "description": "Web design deposit",
    "expires_at": "2026-08-24T00:00:00Z",
    "status": "ACTIVE",
    "public_slug": "PLK-7X29QK",
    "public_url": "https://pay.infinitypay.me/pay/PLK-7X29QK",
    "created_at": "2026-08-14T09:00:00Z",
    "updated_at": "2026-08-14T09:00:00Z"
  }
}`}</CodeBlock>
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          Share <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">public_url</code> with
          your customer directly — it already points at Infinity&apos;s own payment page, so nothing else on your
          side needs to render a payment form. You don&apos;t choose which methods are accepted — the customer picks
          Mobile Money Push, Selcom Pesa, or Scan QR / TanQR themselves on that page.
        </p>
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
              {[
                ["ACTIVE", "Payable — the default state on creation."],
                ["PAID", "A collection against this link succeeded. Terminal."],
                ["EXPIRED", "expires_at has passed. Computed lazily on read, not by a background job."],
                ["CANCELLED", "Cancelled by the business before being paid."],
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

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Building your own checkout UI</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          If you&apos;d rather render your own checkout page instead of redirecting to{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">public_url</code>, fetch
          the link&apos;s public details, then call{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">POST /public/payment-links/{"{public_slug}"}/pay</code> once
          the customer picks a method:
        </p>
        <div className="space-y-4">
          <CodeBlock language="json — GET /public/payment-links/PLK-7X29QK">{`{
  "success": true,
  "data": {
    "merchant_name": "Amani Store",
    "amount": "25000.00",
    "currency": "TZS",
    "description": "Web design deposit",
    "customer_name": "Grace Mwakalinga",
    "customer_phone": "+255754221908",
    "expires_at": "2026-08-24T00:00:00Z",
    "status": "ACTIVE"
  }
}`}</CodeBlock>
          <CodeBlock language="json — POST /public/payment-links/PLK-7X29QK/pay">{`{
  "method": "WALLET_PUSH",
  "customer_phone": "+255754221908"
}`}</CodeBlock>
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">method</code> is one
          of <code className="font-mono text-xs">WALLET_PUSH</code>, <code className="font-mono text-xs">SELCOM_PESA</code>,
          or <code className="font-mono text-xs">TANQR</code> — same three methods documented on the{" "}
          <a href="/developers/collections" className="text-primary font-semibold hover:underline">Collections API</a> page.
          The response comes back <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">pending</code>,
          not <code className="font-mono text-xs">successful</code> — poll{" "}
          <code className="font-mono text-xs">GET /public/payment-links/{"{public_slug}"}/collections/{"{collection_id}"}/status</code> or
          listen for the webhook, exactly like every other collection method.
        </p>
      </section>

      <DocsPager currentHref="/developers/payment-links" />
    </div>
  );
}
