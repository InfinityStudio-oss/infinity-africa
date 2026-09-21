import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  title: "Collections API",
};

function Code({ children }: { children: React.ReactNode }) {
  return <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">{children}</code>;
}

export default function CollectionsApiPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">API Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Collections API</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Three ways to collect a payment, all backed by the same real Selcom Checkout integration and the same
        reversal-safe crediting lifecycle: hand the customer an Infinity Payment Page, push a prompt straight to
        their phone, or hand them a QR code to scan.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Which flow should I use?</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-outline-variant/40 p-4">
            <p className="text-sm font-semibold text-on-surface mb-1">Infinity Payment Page</p>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              Recommended for ecommerce websites, mobile apps, and invoices. You don&apos;t pick a payment method
              — Infinity hosts a page where the customer chooses Mobile Money Push, Selcom Pesa, or Scan QR
              themselves.
            </p>
          </div>
          <div className="rounded-xl border border-outline-variant/40 p-4">
            <p className="text-sm font-semibold text-on-surface mb-1">Direct Wallet Push / Selcom Pesa</p>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              Best when you already have the customer&apos;s phone number and want the fastest checkout — sends
              a real prompt immediately, no redirect.
            </p>
          </div>
          <div className="rounded-xl border border-outline-variant/40 p-4">
            <p className="text-sm font-semibold text-on-surface mb-1">Scan QR / TanQR</p>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              Best for POS/counter payments, delivery, or any screen where a customer scans instead of typing a
              phone number.
            </p>
          </div>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Endpoints</h2>
        <div className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-5">
          <EndpointRow method="POST" path="/v1/collections" description="Create an Infinity Payment Page — returns payment_url." auth="Idempotency-Key required" />
          <EndpointRow method="POST" path="/v1/collections/wallet-push" description="Send a Mobile Money Push prompt immediately." auth="Idempotency-Key required" />
          <EndpointRow method="POST" path="/v1/collections/selcom-pesa" description="Send a Selcom Pesa prompt immediately." auth="Idempotency-Key required" />
          <EndpointRow method="POST" path="/v1/collections/qr" description="Create a Scan QR / TanQR collection." auth="Idempotency-Key required" />
          <EndpointRow method="GET" path="/v1/collections/{collection_id}" description="Check a collection's current status." auth="API key or dashboard" />
          <EndpointRow method="POST" path="/v1/collections/{collection_id}/refresh-status" description="Force a fresh check with the provider." auth="API key or dashboard" />
        </div>
        <p className="text-xs text-on-surface-variant mt-3">
          Every <Code>collection_id</Code> above works with both status endpoints, regardless of which of the
          four creation endpoints returned it.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">1. Infinity Payment Page</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Create a collection, redirect your customer to the returned <Code>payment_url</Code>, and let Infinity
          handle the rest. Your backend never sees a phone number, a QR code, or a &quot;method&quot; field — the
          customer picks Mobile Money Push, Selcom Pesa, or Scan QR / TanQR on that page.
        </p>
        <ol className="text-sm text-on-surface-variant leading-relaxed list-decimal list-inside space-y-1 mb-4">
          <li>Customer checks out on your website/app.</li>
          <li>Your backend calls <Code>POST /v1/collections</Code>.</li>
          <li>Infinity returns <Code>payment_url</Code>.</li>
          <li>Redirect the customer there.</li>
          <li>Customer chooses a payment method and pays.</li>
          <li>Infinity sends a webhook when the status changes (see the Webhooks page).</li>
          <li>Mark the order paid only once you see <Code>collection.successful</Code>.</li>
        </ol>
        <div className="space-y-4">
          <CodeBlock language="json — POST /v1/collections">{`{
  "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
  "amount": 50000,
  "currency": "TZS",
  "customer_name": "Grace Mwakalinga",
  "customer_phone": "255712345678",
  "customer_email": "grace@example.com",
  "reference": "ORDER-4821",
  "description": "Payment for order ORDER-4821",
  "redirect_url": "https://merchantstore.co.tz/thank-you",
  "cancel_url": "https://merchantstore.co.tz/payment-failed"
}`}</CodeBlock>
          <CodeBlock language="json — 202 Accepted">{`{
  "success": true,
  "data": {
    "collection_id": "9b7e2c1a-...",
    "reference": "ORDER-4821",
    "status": "created",
    "payment_url": "https://infinitypay.me/pay/8f3a1c2b"
  }
}`}</CodeBlock>
        </div>
        <Callout tone="warning" title="webhook_url is not per-request">
          The <Code>webhook_url</Code> field is accepted for forward compatibility but not yet used — configure
          your webhook URL once for your whole account via <Code>PATCH /v1/merchant/webhook-config</Code> or the
          Merchant Portal&apos;s Webhooks page. See the Webhooks page for details.
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">2. Direct Wallet Push / Selcom Pesa</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Same shape, two endpoints — <Code>/wallet-push</Code> for a general Mobile Money Push (STK/USSD, Selcom
          auto-detects the customer&apos;s carrier), <Code>/selcom-pesa</Code> to push specifically to a Selcom
          Pesa wallet. <Code>phone</Code> is required for both — a push has nowhere to go without one.
        </p>
        <Callout tone="warning" title="A 202/&quot;processing&quot; response means the prompt was sent — nothing more">
          Wallet push and Selcom Pesa push success only mean Selcom accepted the push request. It does{" "}
          <strong>not</strong> mean the customer approved it or that funds moved. Never mark an order paid from
          this response — wait for <Code>collection.successful</Code> (webhook) or poll{" "}
          <Code>GET /v1/collections/{"{collection_id}"}</Code> until <Code>status</Code> is{" "}
          <Code>successful</Code>.
        </Callout>
        <div className="space-y-4 mt-4">
          <CodeBlock language="json — POST /v1/collections/wallet-push">{`{
  "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
  "amount": 50000,
  "currency": "TZS",
  "phone": "255712345678",
  "customer_name": "Grace Mwakalinga",
  "reference": "ORDER-4821",
  "description": "Payment for order ORDER-4821"
}`}</CodeBlock>
          <CodeBlock language="json — 202 Accepted">{`{
  "success": true,
  "data": {
    "collection_id": "9b7e2c1a-...",
    "reference": "ORDER-4821",
    "status": "processing",
    "message": "Payment prompt sent. Please approve on your phone."
  }
}`}</CodeBlock>
        </div>
        <p className="text-xs text-on-surface-variant leading-relaxed mt-3">
          <Code>POST /v1/collections/selcom-pesa</Code> takes and returns the exact same shape — only the prompt
          message differs (&quot;Selcom Pesa prompt sent. Please approve in your Selcom Pesa app.&quot;).
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">3. Scan QR / TanQR</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          <Code>customer_phone</Code> is optional here — nothing gets pushed to it. <Code>qr_payload</Code> and{" "}
          <Code>payment_token</Code> are exactly what Selcom&apos;s own order-creation response returned:
          Infinity never generates its own payment QR. Render <Code>qr_payload</Code> as a scannable code
          client-side (any standard QR library) exactly as received — don&apos;t re-encode it, and don&apos;t
          build your own payload from the order details.
        </p>
        <div className="space-y-4">
          <CodeBlock language="json — POST /v1/collections/qr">{`{
  "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
  "amount": 50000,
  "currency": "TZS",
  "customer_name": "Grace Mwakalinga",
  "reference": "ORDER-4821",
  "description": "Counter payment"
}`}</CodeBlock>
          <CodeBlock language="json — 202 Accepted">{`{
  "success": true,
  "data": {
    "collection_id": "9b7e2c1a-...",
    "reference": "ORDER-4821",
    "status": "processing",
    "payment_token": "80008000",
    "qr_payload": "<exact Selcom-returned qr value>",
    "expires_at": null
  }
}`}</CodeBlock>
        </div>
        <p className="text-xs text-on-surface-variant leading-relaxed mt-3">
          <Code>expires_at</Code> is always <Code>null</Code> today — Selcom&apos;s order-creation response
          doesn&apos;t include a QR/token expiry field, so this is never fabricated. Don&apos;t assume the code is
          time-limited unless a future response actually returns one.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Checking status</h2>
        <div className="space-y-4">
          <CodeBlock language="json — GET /v1/collections/{collection_id}?merchant_id=... — 200 OK">{`{
  "success": true,
  "data": {
    "collection_id": "9b7e2c1a-...",
    "reference": "ORDER-4821",
    "status": "pending_clearance",
    "amount": 50000,
    "currency": "TZS",
    "method": "wallet_push",
    "provider_payment_status": "COMPLETED",
    "created_at": "2026-08-24T09:00:00+03:00",
    "updated_at": "2026-08-24T09:02:00+03:00"
  }
}`}</CodeBlock>
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          <Code>POST /v1/collections/{"{collection_id}"}/refresh-status</Code> forces a fresh check with Selcom
          instead of waiting for a webhook — safe to call repeatedly. It never double-credits or double-reverses,
          and is a no-op if the customer hasn&apos;t picked a method yet on an Infinity Payment Page collection.
        </p>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Status lifecycle</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          See the <a href="/developers/webhooks" className="text-primary font-semibold hover:underline">Webhooks</a> page
          for the full lifecycle table and the merchant order-payment rule. In short:{" "}
          <strong className="text-on-surface">only mark an order paid when status is <Code>successful</Code></strong> —
          never from <Code>created</Code>, <Code>processing</Code>, a QR/token being returned, or a wallet-push
          resultcode of <Code>000</Code>.
        </p>
        <Callout title="Webhooks are the reliable way to resolve a collection">
          Don&apos;t block a customer-facing flow on polling — subscribe to{" "}
          <Code>collection.successful</Code>/<Code>collection.failed</Code>/<Code>collection.reversed</Code> on
          the{" "}
          <a href="/developers/webhooks" className="text-primary font-semibold hover:underline">
            Webhooks
          </a>{" "}
          page instead.
        </Callout>
      </section>

      <DocsPager currentHref="/developers/collections" />
    </div>
  );
}
