import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  title: "Dynamic QR API",
};

export default function DynamicQrApiPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">API Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Dynamic QR API</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Generate a scannable QR code for a specific amount — no customer phone number required. Good for in-person
        checkouts, printed receipts, or a payment screen a customer scans with any mobile money app.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Endpoint</h2>
        <div className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-5">
          <EndpointRow
            method="POST"
            path="/v1/collections/dynamic-qr"
            description="Generate a Dynamic QR collection."
            auth="API key or dashboard"
          />
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Authentication</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Call this endpoint from your own backend with an API key that has the{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">collections:write</code>{" "}
          scope, or from the Merchant Portal dashboard (signed-in session). Generate a key on the{" "}
          <a href="/dashboard/login" className="text-primary font-semibold hover:underline">
            Merchant Portal
          </a>{" "}
          — see{" "}
          <a href="/developers/authentication" className="text-primary font-semibold hover:underline">
            API Key Authentication
          </a>
          .
        </p>
        <CodeBlock language="bash — cURL">{`curl -X POST https://api.infinitypay.me/v1/collections/dynamic-qr \\
  -H "Authorization: Bearer inf_live_xxxxxxxxxxxxx" \\
  -H "Idempotency-Key: 6f1e2a3b-..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "amount": "15000.00",
    "currency": "TZS",
    "merchant_reference": "ORDER-4821"
  }'`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Response</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Unlike a push collection, no <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">customer_phone</code> is
          required or returned. The response includes a{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">qr_payload</code> string —
          render it as a QR code with any client-side QR library — and a{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">qr_expires_at</code> timestamp.
        </p>
        <CodeBlock language="json — 202 Accepted">{`{
  "success": true,
  "data": {
    "id": "2d4f8a91-...",
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "method": "DYNAMIC_QR",
    "amount": "15000.00",
    "currency": "TZS",
    "status": "processing",
    "qr_payload": "selcompay://qr?ref=MOCK-SELCOM-7C1E&amount=15000&currency=TZS",
    "qr_expires_at": "2026-08-14T09:05:00Z",
    "qr_image_url": null,
    "expires_at": "2026-08-14T09:05:00Z",
    "message": "Scan the QR code with a mobile money app to complete payment.",
    "provider": "mock_selcom",
    "provider_reference": "MOCK-SELCOM-7C1E",
    "transaction_reference": "TXN-...",
    "created_at": "2026-08-14T09:00:00Z"
  }
}`}</CodeBlock>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">qr_image_url</code> is
          always <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">null</code> today
          — no server-rendered QR image is generated yet, so render{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">qr_payload</code> client-side
          instead. <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">expires_at</code> is
          the same value as <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">qr_expires_at</code>,
          shared with the push endpoints&apos; response shape.
        </p>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Resolving a scan</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          A Dynamic QR collection starts as{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">processing</code> and
          resolves once the customer scans and confirms on their end. Listen for{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">collection.success</code> /{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">collection.failed</code>, or
          poll{" "}
          <a href="/developers/transaction-status" className="text-primary font-semibold hover:underline">
            Transaction Status
          </a>{" "}
          by reference. The code itself expires at <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">qr_expires_at</code> —
          generate a fresh one if the customer doesn&apos;t scan in time.
        </p>
        <Callout title="Regenerate on expiry, don't reuse an old QR">
          A scanned-but-expired code will be rejected by the customer&apos;s wallet app. If{" "}
          <code className="font-mono text-xs">qr_expires_at</code> has passed, call this endpoint again for a new code
          rather than re-displaying the old one.
        </Callout>
      </section>

      <DocsPager currentHref="/developers/dynamic-qr" />
    </div>
  );
}
