import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  title: "Webhooks",
};

const EVENTS: Array<{ event: string; description: string; live: boolean }> = [
  { event: "collection.success", description: "A collection reached successful — the business wallet was credited. The only event safe to mark an order paid from.", live: true },
  { event: "collection.failed", description: "A push or QR collection was declined, rejected, or timed out.", live: true },
  { event: "collection.pending_review", description: "Held before crediting — the payer's phone matched the business's own registered phone (self-payment/\"own till\" risk). Requires Super Admin review.", live: true },
  { event: "collection.reversed", description: "A previously successful collection was reversed by the provider after settlement — the wallet credit was clawed back.", live: true },
  { event: "disbursement.success", description: "A payout was delivered.", live: true },
  { event: "disbursement.failed", description: "A payout was declined; its balance reservation was reversed.", live: true },
  { event: "disbursement.reversed", description: "A previously successful payout was reversed by the provider after settlement.", live: true },
  { event: "payment_link.paid", description: "A payment link (including one generated from an invoice) was paid.", live: true },
  { event: "payment_link.payment_reversed", description: "A payment link's PAID status was reopened because its collection was reversed.", live: true },
  { event: "invoice.paid", description: "An invoice reached PAID.", live: true },
  { event: "collection.pending", description: "Reserved for a future intermediate collection state.", live: false },
  { event: "collection.processing", description: "Reserved — a push was sent or a QR/token was generated; not emitted as its own event yet (visible via GET/refresh-status instead).", live: false },
  { event: "collection.cancelled", description: "Reserved — no code path sets a collection to cancelled yet.", live: false },
  { event: "invoice.overdue", description: "Reserved for a scheduled past-due sweep.", live: false },
  { event: "payment_link.created", description: "Reserved.", live: false },
  { event: "payment_link.expired", description: "Reserved for a scheduled expiry sweep.", live: false },
  { event: "refund.succeeded", description: "Reserved — refunds aren't issued yet.", live: false },
  { event: "refund.failed", description: "Reserved.", live: false },
  { event: "chargeback.opened", description: "Reserved.", live: false },
  { event: "chargeback.resolved", description: "Reserved.", live: false },
];

const LIFECYCLE: Array<{ status: string; meaning: string }> = [
  { status: "created", meaning: "Collection created (an Infinity Payment Page with no method chosen yet). Payment has not started." },
  { status: "processing", meaning: "A prompt was sent or a QR/token was generated. The customer has not yet approved anything." },
  { status: "pending_clearance", meaning: "The provider signaled completion, but a review step still applies before funds become available (currently: self-payment/\"own till\" risk review). Not yet safe to treat as paid." },
  { status: "successful", meaning: "Final, safe, completed state. The wallet was credited. The only status safe to mark an order paid from." },
  { status: "failed", meaning: "The attempt did not complete. Not payable, not credited." },
  { status: "cancelled", meaning: "The attempt was cancelled. Not payable, not credited." },
  { status: "reversed", meaning: "Was successful, then clawed back by the provider after settlement. Not credited — treat exactly like a failed payment." },
];

export default function WebhooksPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">API Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Webhooks</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        InfinityPay notifies your server the moment a collection resolves, a payout completes, or an invoice gets paid —
        so you don&apos;t have to poll. Configure your endpoint once; every event after that is pushed to you.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Configuring your endpoint</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Set your webhook URL and choose which events to subscribe to from the dashboard&apos;s{" "}
          <strong>Webhooks</strong> page — generate a signing secret there too (shown once, like an API key), and use
          the page&apos;s <strong>Send Test Webhook</strong> button to confirm your endpoint is reachable before
          going live. The same page shows the status of your most recent delivery attempt.
        </p>
        <EndpointRow method="GET" path="/v1/merchant/webhook-config" description="Read your current webhook URL, subscribed events, and whether a secret is set." auth="MERCHANT_ADMIN, MERCHANT_STAFF" />
        <div className="mt-3">
          <EndpointRow method="PATCH" path="/v1/merchant/webhook-config" description="Set the URL/events, and optionally regenerate the signing secret (returned once, in the response)." auth="MERCHANT_ADMIN, DEVELOPER" />
        </div>
        <div className="mt-3">
          <EndpointRow method="POST" path="/v1/merchant/webhook-config/test" description="Send a signed sample payload to your configured URL right now and report the result." auth="MERCHANT_ADMIN, DEVELOPER" />
        </div>
        <div className="mt-3">
          <EndpointRow method="GET" path="/v1/merchant/webhook-events" description="List your own outbound delivery queue." auth="MERCHANT_ADMIN, MERCHANT_STAFF" />
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Event types</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          The events below are the ones your integration should actually handle. A few additional names are reserved
          in the schema for features on the roadmap (refunds, chargebacks, scheduled sweeps) — you&apos;ll see them
          in the enum, but nothing emits them yet.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border border-outline-variant/40 rounded-xl overflow-hidden">
            <thead className="bg-surface-container-low">
              <tr>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Event</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Fires when</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {EVENTS.map((item) => (
                <tr key={item.event} className={item.live ? "" : "opacity-50"}>
                  <td className="px-4 py-2.5 font-mono text-xs text-on-surface">{item.event}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant">
                    {item.description}
                    {!item.live && <span className="ml-2 text-[11px] font-semibold text-on-surface-variant/70">(reserved)</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Status lifecycle</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          The <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">status</code> field
          on a collection webhook (and on <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">GET /v1/collections/{"{id}"}</code>)
          is always one of these seven values:
        </p>
        <div className="overflow-x-auto mb-4">
          <table className="w-full text-left text-sm border border-outline-variant/40 rounded-xl overflow-hidden">
            <thead className="bg-surface-container-low">
              <tr>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Status</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Meaning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {LIFECYCLE.map((item) => (
                <tr key={item.status}>
                  <td className="px-4 py-2.5 font-mono text-xs text-on-surface whitespace-nowrap">{item.status}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant">{item.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Callout tone="warning" title="Mark an order paid only on collection.successful">
          Never mark an order paid from a wallet-push prompt being sent, a QR/token being generated,
          or a resultcode of <code className="font-mono text-xs">000</code> on the initial push response — all of
          those only mean the provider <em>accepted the request</em>, not that the customer paid. Wait for{" "}
          <code className="font-mono text-xs">collection.successful</code> (webhook) or poll{" "}
          <code className="font-mono text-xs">GET /v1/collections/{"{id}"}</code> until{" "}
          <code className="font-mono text-xs">status</code> is <code className="font-mono text-xs">successful</code>.
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Payload shape</h2>
        <CodeBlock language="json — POST to your webhook_url">{`{
  "event": "collection.successful",
  "merchant_code": "27048391",
  "collection_id": "col_xxxxx",
  "transaction_id": "txn_xxxxx",
  "reference": "ORDER-4821",
  "merchant_reference": "ORDER-4821",
  "amount": 50000,
  "fee": 750,
  "net_amount": 49250,
  "currency": "TZS",
  "status": "successful",
  "timestamp": "2026-08-23T10:00:00+03:00"
}`}</CodeBlock>
        <p className="text-xs text-on-surface-variant leading-relaxed mt-3">
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">merchant_code</code> is
          your ID — identification only, never a secret and never usable as an API key.{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">reference</code> and{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">merchant_reference</code>{" "}
          are the same value — kept as two keys so existing integrations parsing{" "}
          <code className="font-mono text-xs">reference</code> keep working.
        </p>
        <p className="text-xs text-on-surface-variant leading-relaxed mt-3">
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">fee</code>/<code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">net_amount</code> are
          only present once a fee has actually been calculated (i.e. from{" "}
          <code className="font-mono text-xs">collection.successful</code>/<code className="font-mono text-xs">collection.reversed</code> onward)
          — never fabricated for an event where no fee exists yet.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Verifying a delivery</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Every delivery is signed with your&apos;s webhook secret, sent as{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">X-Infinity-Signature</code>: an
          HMAC-SHA256 hex digest of the exact raw request body. Recompute it and compare — don&apos;t trust a
          delivery that doesn&apos;t match, and use a constant-time comparison to avoid leaking timing information.
        </p>
        <div className="space-y-4">
          <CodeBlock language="python">{`import hashlib
import hmac

def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)`}</CodeBlock>
          <CodeBlock language="javascript — Node.js">{`const crypto = require("crypto");

function verifySignature(rawBody, signature, secret) {
  const expected = crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
  const a = Buffer.from(expected, "utf8");
  const b = Buffer.from(signature || "", "utf8");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// Express example — read the raw body BEFORE any JSON-parsing middleware
// runs, since the signature is computed over the exact raw bytes:
app.post(
  "/api/infinity/webhook",
  express.raw({ type: "application/json" }),
  (req, res) => {
    const signature = req.header("X-Infinity-Signature");
    if (!verifySignature(req.body, signature, process.env.INFINITY_WEBHOOK_SECRET)) {
      return res.status(401).send("invalid signature");
    }
    const event = JSON.parse(req.body);
    // ... handle event.event / event.status / event.collection_id
    res.status(200).send("ok");
  },
);`}</CodeBlock>
        </div>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Retries</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Every event is recorded to your delivery queue the moment it happens. Automatic retry-with-backoff delivery
          is on the roadmap but not live yet — for now, use{" "}
          <strong>Send Test Webhook</strong> on the Portal&apos;s Webhooks page to confirm your endpoint responds
          correctly, and{" "}
          <a href="/developers/transaction-status" className="text-primary font-semibold hover:underline">
            Transaction Status
          </a>{" "}
          to poll as a fallback. Respond quickly to real deliveries once retries ship — do your processing
          asynchronously after returning <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">200</code>,
          rather than making InfinityPay wait on it.
        </p>
        <Callout title="Design for at-least-once delivery">
          Once automatic retries are live, treat every delivery as at-least-once, not exactly-once. Key your own
          processing off the resource ID inside <code className="font-mono text-xs">payload</code> (e.g.{" "}
          <code className="font-mono text-xs">collection_id</code>) and make handling that ID idempotent now, so a
          duplicate delivery is a safe no-op later.
        </Callout>
      </section>

      <DocsPager currentHref="/developers/webhooks" />
    </div>
  );
}
