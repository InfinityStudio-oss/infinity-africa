import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  alternates: { canonical: "/developers/dynamic-qr" },
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
            path="/v1/collections/qr"
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
          scope, or from the dashboard (signed-in session). Generate a key on the{" "}
          <a href="/dashboard/login" className="text-primary font-semibold hover:underline">
            dashboard
          </a>{" "}
          — see{" "}
          <a href="/developers/authentication" className="text-primary font-semibold hover:underline">
            API Key Authentication
          </a>
          .
        </p>
        <CodeBlock language="bash — cURL">{`curl -X POST https://api.infinitypay.me/v1/collections/qr \\
  -H "Authorization: Bearer sk_live_xxxxxxxxxxxxx" \\
  -H "Idempotency-Key: 6f1e2a3b-..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "amount": "15000.00",
    "currency": "TZS",
    "reference": "ORDER-4821"
  }'`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Response</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Unlike a push collection, no <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">customer_phone</code> is
          required. You get back a <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">payment_token</code> and a{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">qr_payload</code> — render the payload as a QR code with any
          client-side QR library.
        </p>
        <CodeBlock language="json — 202 Accepted">{`{
  "success": true,
  "data": {
    "collection_id": "2d4f8a91-6c7b-4e55-91a8-7d3f2b1c9e04",
    "reference": "ORDER-4821",
    "status": "processing",
    "payment_token": "9f2bc4d1e8a7b3c6",
    "qr_payload": "https://checkout.selcom.net/t/9f2bc4d1e8a7b3c6",
    "expires_at": null
  }
}`}</CodeBlock>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">expires_at</code> is always{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">null</code>. Selcom&apos;s own response carries no expiry for a
          QR or token, so InfinityPay does not invent one — do not assume the code is
          time-limited, and do not build a countdown on this field. No server-rendered
          QR image is produced either; render <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">qr_payload</code> yourself.
        </p>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Resolving a scan</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          A QR collection starts as{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">processing</code> and resolves once the customer scans and
          confirms. Listen for{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">collection.success</code> /{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">collection.failed</code>, or poll{" "}
          <a href="/developers/transaction-status" className="text-primary font-semibold hover:underline">
            Transaction Status
          </a>{" "}
          by reference. Never mark an order paid from the{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">202</code> — it means the code was created, not that anyone has
          paid.
        </p>
        <Callout title="There is no expiry to code against">
          Selcom returns no expiry for a QR, so <code className="font-mono text-xs">expires_at</code>{" "}
          is always <code className="font-mono text-xs">null</code>. If you need a code to stop
          being payable, track that yourself and generate a fresh collection — do not rely on
          this API to expire one for you.
        </Callout>
      </section>

      <DocsPager currentHref="/developers/dynamic-qr" />
    </div>
  );
}
