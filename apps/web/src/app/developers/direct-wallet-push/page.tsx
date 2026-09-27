import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  alternates: { canonical: "/developers/direct-wallet-push" },
  title: "Direct Wallet Push — Partner Integration",
  description:
    "End-to-end integration guide for collecting payments with InfinityPay Direct Wallet Push: authentication, idempotency, webhooks, failure reasons and go-live steps.",
};

function Code({ children }: { children: React.ReactNode }) {
  return <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">{children}</code>;
}

const REQUEST_FIELDS: Array<{ field: string; required: string; notes: React.ReactNode }> = [
  { field: "amount", required: "Yes", notes: "Decimal string, e.g. \"5000.00\"." },
  { field: "phone", required: "Yes", notes: "The customer's mobile money number." },
  { field: "currency", required: "No", notes: <>Defaults to <Code>TZS</Code>.</> },
  { field: "customer_name", required: "No", notes: "Shown on the merchant's records." },
  { field: "reference", required: "No", notes: "Your order or invoice id. Echoed back on every response and webhook." },
  { field: "description", required: "No", notes: "Free text." },
  {
    field: "merchant_id",
    required: "No",
    notes: (
      <>
        <strong>You do not need this.</strong> Your API key already identifies the merchant. Accepted if sent, and
        rejected if it is not the key&apos;s own merchant.
      </>
    ),
  },
];

const STATUSES: Array<{ status: string; meaning: string; action: string }> = [
  { status: "processing", meaning: "Prompt sent, customer has not acted yet.", action: "Wait for the webhook." },
  { status: "successful", meaning: "Paid, and the merchant wallet is credited.", action: "Fulfil the order." },
  { status: "failed", meaning: "Terminal failure.", action: "Read failure_reason_code." },
  { status: "pending_clearance", meaning: "Held for review.", action: "Wait. Do not fulfil." },
  { status: "reversed", meaning: "Reversed after completing.", action: "Reverse your fulfilment." },
];

const REASONS: Array<{ code: string; meaning: string }> = [
  { code: "user_cancelled", meaning: "The customer cancelled the prompt." },
  { code: "provider_declined", meaning: "Declined by the payment provider." },
  { code: "reversed", meaning: "Reversed after it had completed." },
  { code: "expired", meaning: "Expired before the customer approved it." },
  { code: "provider_unavailable", meaning: "Provider unreachable. Retryable." },
  { code: "unknown_provider_error", meaning: "The cause could not be identified." },
  { code: "insufficient_balance", meaning: "Not enough balance in the wallet." },
  { code: "wrong_pin", meaning: "Wrong PIN, or authorization failed." },
  { code: "timeout", meaning: "Authorization timed out." },
];

export default function DirectWalletPushPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Partner Integration</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Direct Wallet Push</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        A complete integration guide for a billing platform, ecommerce site, or app collecting payments on behalf of
        InfinityPay merchants — from the first API call through to handling a failed payment.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">How it fits together</h2>
        <CodeBlock language="text">{`Your system ──API key──▶ InfinityPay ──▶ Mobile money ──▶ Customer's wallet
      ▲                        │
      └──────  webhook  ───────┘`}</CodeBlock>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          You integrate with InfinityPay and nothing else. InfinityPay holds the provider relationships and reaches
          them from its own approved infrastructure. You never hold, see, or configure provider credentials.
        </p>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-3">
          A merchant&apos;s IP allowlist governs access <em>to the InfinityPay API</em>. It is unrelated to any
          provider-side allowlist, which covers InfinityPay&apos;s own servers and is not your concern.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">What the merchant sets up first</h2>
        <ol className="text-sm text-on-surface-variant leading-relaxed space-y-2 list-decimal pl-5">
          <li>Creates an InfinityPay account and completes verification.</li>
          <li>
            Generates API credentials at <Code>/portal/api-credentials</Code>. Sandbox keys work immediately; live
            keys become available once the account is approved, verified, and priced — there is no per-key approval
            step.
          </li>
          <li>Gives you the secret key.</li>
          <li>
            Sets a <strong>webhook URL</strong> and generates a <strong>signing secret</strong> at{" "}
            <Code>/portal/webhooks</Code>.
          </li>
        </ol>
        <Callout title="The webhook URL is not optional in practice">
          With no webhook URL configured, no events are sent at all — silently, with no error. If you plan to react
          to payment outcomes rather than poll for them, confirm the merchant has set one before going live.
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Authentication</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Send the secret key as a bearer token, or as <Code>X-API-Key</Code> — both are accepted.
        </p>
        <CodeBlock language="bash">{`Authorization: Bearer sk_live_YOUR_SECRET_KEY_HERE`}</CodeBlock>
        <ul className="text-sm text-on-surface-variant leading-relaxed mt-4 space-y-2 list-disc pl-5">
          <li>
            <Code>sk_live_…</Code> moves real money. <Code>sk_test_…</Code> is sandbox — no provider call, no money.
          </li>
          <li>
            <Code>pk_…</Code> is a public identifier, <strong>not a credential</strong>. It cannot authenticate and
            is rejected if sent as a token.
          </li>
          <li>
            The secret is shown once at creation and stored only as a hash. It cannot be recovered — rotate if lost.
          </li>
          <li>Server-side only. Never ship a secret key in a browser or mobile app.</li>
        </ul>
        <Callout title="There is no request signing today">
          Requests are authenticated by the bearer key over HTTPS, optionally narrowed by an IP allowlist.
          InfinityPay does <strong>not</strong> currently verify an HMAC signature on inbound API requests — do not
          build one expecting it to be checked. Outbound webhooks <em>are</em> signed; that is separate and covered
          below.
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Sending a push</h2>
        <EndpointRow
          method="POST"
          path="/v1/collections/wallet-push"
          description="Send a payment prompt to the customer's phone."
          auth="API key (collections:write)"
        />
        <div className="mt-4">
          <CodeBlock language="bash">{`curl -X POST https://api.infinitypay.me/v1/collections/wallet-push \\
  -H "Authorization: Bearer sk_live_YOUR_SECRET_KEY_HERE" \\
  -H "Idempotency-Key: 8f1c2d3e-4b5a-6c7d-8e9f-0a1b2c3d4e5f" \\
  -H "Content-Type: application/json" \\
  -d '{
    "amount": "5000.00",
    "currency": "TZS",
    "phone": "+255712345678",
    "customer_name": "Asha Mushi",
    "reference": "INV-2026-000412",
    "description": "March broadband subscription"
  }'`}</CodeBlock>
        </div>

        <div className="overflow-x-auto mt-6">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-outline-variant/40">
                <th className="py-2 pr-4 font-semibold text-on-surface">Field</th>
                <th className="py-2 pr-4 font-semibold text-on-surface">Required</th>
                <th className="py-2 font-semibold text-on-surface">Notes</th>
              </tr>
            </thead>
            <tbody>
              {REQUEST_FIELDS.map((row) => (
                <tr key={row.field} className="border-b border-outline-variant/20 align-top">
                  <td className="py-2 pr-4"><Code>{row.field}</Code></td>
                  <td className="py-2 pr-4 text-on-surface-variant">{row.required}</td>
                  <td className="py-2 text-on-surface-variant">{row.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          <Code>Idempotency-Key</Code> is a required <em>header</em>, not a body field.
        </p>

        <div className="mt-6">
          <CodeBlock language="json">{`{
  "success": true,
  "data": {
    "collection_id": "3f2a8c1e-...",
    "reference": "INV-2026-000412",
    "status": "processing",
    "message": "Payment prompt sent. Please approve on your phone."
  }
}`}</CodeBlock>
        </div>

        <Callout title="202 means the prompt was sent, not that payment succeeded">
          Never mark an order paid from this response. Wait for the <Code>collection.success</Code> webhook, or poll{" "}
          <Code>GET /v1/collections/{"{collection_id}"}</Code>.
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Idempotency</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Retry with the <strong>same</strong> <Code>Idempotency-Key</Code> and you get the original result back — no
          second prompt to the customer, no second payment attempt. Reusing a key with a <em>different</em> body is
          rejected rather than silently returning the wrong result.
        </p>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          Generate one key per payment attempt and reuse it for every retry of that attempt. Do not reuse it for a
          genuinely new payment.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Webhooks</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Events relevant to this flow: <Code>collection.success</Code>, <Code>collection.failed</Code>, and{" "}
          <Code>collection.pending_review</Code>. Full details, signature verification examples and the retry
          schedule are on the{" "}
          <a href="/developers/webhooks" className="text-primary font-semibold hover:underline">
            Webhooks
          </a>{" "}
          page.
        </p>
        <CodeBlock language="json">{`{
  "event": "collection.failed",
  "merchant_code": "27048391",
  "collection_id": "3f2a8c1e-...",
  "reference": "INV-2026-000412",
  "merchant_reference": "INV-2026-000412",
  "amount": "5000.00",
  "currency": "TZS",
  "status": "failed",
  "failure_reason_code": "user_cancelled",
  "failure_reason_message": "The customer cancelled the payment.",
  "failed_at": "2026-09-27T09:14:22Z",
  "timestamp": "2026-09-27T09:14:22Z"
}`}</CodeBlock>
        <h3 className="text-base font-semibold text-on-surface mt-8 mb-3">Headers on every delivery</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-outline-variant/40">
                <th className="py-2 pr-4 font-semibold text-on-surface">Header</th>
                <th className="py-2 font-semibold text-on-surface">Purpose</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-outline-variant/20 align-top">
                <td className="py-2 pr-4"><Code>X-Infinity-Signature</Code></td>
                <td className="py-2 text-on-surface-variant">
                  HMAC-SHA256 hex digest of the exact raw body, keyed with the webhook secret.
                </td>
              </tr>
              <tr className="border-b border-outline-variant/20 align-top">
                <td className="py-2 pr-4"><Code>X-Infinity-Event</Code></td>
                <td className="py-2 text-on-surface-variant">
                  The event name, e.g. <Code>collection.success</Code>.
                </td>
              </tr>
              <tr className="border-b border-outline-variant/20 align-top">
                <td className="py-2 pr-4"><Code>X-Infinity-Delivery</Code></td>
                <td className="py-2 text-on-surface-variant">
                  Unique per event. Deduplicate on this — deliveries are at-least-once.
                </td>
              </tr>
              <tr className="border-b border-outline-variant/20 align-top">
                <td className="py-2 pr-4"><Code>X-Infinity-Timestamp</Code></td>
                <td className="py-2 text-on-surface-variant">
                  Unix seconds at send time, for rejecting very old replays. <strong>Not</strong> part of the signed
                  material — verify the signature over the body alone.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3 className="text-base font-semibold text-on-surface mt-8 mb-3">Verifying the signature</h3>
        <CodeBlock language="python">{`import hashlib
import hmac
import json

def handle_webhook(request):
    raw = request.get_data()                      # raw BYTES, before any JSON parse
    sent = request.headers.get("X-Infinity-Signature", "")
    expected = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, sent):   # constant-time
        return "", 401

    payload = json.loads(raw)
    if payload.get("test") or payload.get("sandbox"):
        return "", 200                            # acknowledge, do not fulfil

    # Store it, return 200, then process. Do not process before responding.
    enqueue_for_processing(payload)
    return "", 200`}</CodeBlock>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          Sign the <strong>raw bytes</strong> you received. Parsing the JSON and re-serialising it changes the bytes
          and the digest will not match — this is the single most common integration mistake.
        </p>

        <h3 className="text-base font-semibold text-on-surface mt-8 mb-3">Retries</h3>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Any <Code>2xx</Code> counts as delivered. Anything else — a non-2xx, a timeout, or an unreachable host — is
          retried up to <strong>5 attempts</strong>, spaced <strong>immediately, then after 1, 5, 15 and 30
          minutes</strong>. After the fifth the event is marked failed and is not retried again.
        </p>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          The timeout is <strong>8 seconds</strong>, so return <Code>200</Code> as soon as you have stored the event
          and do your processing afterwards — a slow handler burns a retry. If your endpoint was down long enough to
          exhaust them, poll{" "}
          <a href="/developers/transaction-status" className="text-primary font-semibold hover:underline">
            Transaction Status
          </a>{" "}
          to catch up.
        </p>

        <h3 className="text-base font-semibold text-on-surface mt-8 mb-3">Three kinds of delivery — only one to act on</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-outline-variant/40">
                <th className="py-2 pr-4 font-semibold text-on-surface">Source</th>
                <th className="py-2 pr-4 font-semibold text-on-surface">Marker</th>
                <th className="py-2 font-semibold text-on-surface">Fulfil?</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-outline-variant/20">
                <td className="py-2 pr-4 text-on-surface-variant">Send Test Webhook</td>
                <td className="py-2 pr-4"><Code>&quot;test&quot;: true</Code></td>
                <td className="py-2 text-on-surface-variant">No</td>
              </tr>
              <tr className="border-b border-outline-variant/20">
                <td className="py-2 pr-4 text-on-surface-variant">Sandbox push</td>
                <td className="py-2 pr-4"><Code>&quot;sandbox&quot;: true</Code></td>
                <td className="py-2 text-on-surface-variant">No</td>
              </tr>
              <tr className="border-b border-outline-variant/20">
                <td className="py-2 pr-4 text-on-surface-variant">Live push</td>
                <td className="py-2 pr-4 text-on-surface-variant">Neither field present</td>
                <td className="py-2 font-semibold text-on-surface">Yes</td>
              </tr>
            </tbody>
          </table>
        </div>
        <Callout title="A test delivery deliberately looks like a real success">
          Its body reads <Code>event: collection.success</Code> so that your real handler is what gets exercised. A
          handler keying only on that field would fulfil a fake order — check <Code>test</Code> and{" "}
          <Code>sandbox</Code> explicitly.
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Testing without spending money</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          A sandbox key (<Code>sk_test_…</Code>) queues the same events a live push would, so you can exercise your
          real handler end to end for free. Use <Code>simulate_status</Code> on the create call to choose the
          outcome — <Code>successful</Code>, <Code>failed</Code>, <Code>pending_clearance</Code> or{" "}
          <Code>reversed</Code>.
        </p>
        <CodeBlock language="json">{`{
  "amount": "1000.00",
  "phone": "+255712345678",
  "reference": "TEST-001",
  "simulate_status": "failed"
}`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Statuses</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-outline-variant/40">
                <th className="py-2 pr-4 font-semibold text-on-surface">Status</th>
                <th className="py-2 pr-4 font-semibold text-on-surface">Meaning</th>
                <th className="py-2 font-semibold text-on-surface">What to do</th>
              </tr>
            </thead>
            <tbody>
              {STATUSES.map((row) => (
                <tr key={row.status} className="border-b border-outline-variant/20 align-top">
                  <td className="py-2 pr-4"><Code>{row.status}</Code></td>
                  <td className="py-2 pr-4 text-on-surface-variant">{row.meaning}</td>
                  <td className="py-2 text-on-surface-variant">{row.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Failure reason codes</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          <Code>failure_reason_code</Code> is a closed set, safe to switch on.{" "}
          <Code>failure_reason_message</Code> is a sentence you may show a user. Handle unknown codes gracefully —
          the set can grow.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-outline-variant/40">
                <th className="py-2 pr-4 font-semibold text-on-surface">Code</th>
                <th className="py-2 font-semibold text-on-surface">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {REASONS.map((row) => (
                <tr key={row.code} className="border-b border-outline-variant/20 align-top">
                  <td className="py-2 pr-4"><Code>{row.code}</Code></td>
                  <td className="py-2 text-on-surface-variant">{row.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">IP allowlist (optional)</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          Off by default — a valid key works from any address. Enabled per key in the portal, it restricts that key
          to specific addresses; a request from anywhere else is rejected with a generic error that reveals nothing
          about the allowlist, and the rejection is recorded in the audit log. If you use it, add every egress
          address your servers can present, and update it when your infrastructure changes.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Go-live checklist</h2>
        <ol className="text-sm text-on-surface-variant leading-relaxed space-y-2 list-decimal pl-5">
          <li>Merchant account created, approved and verified.</li>
          <li>Live API key generated. Secret stored server-side only.</li>
          <li>Webhook URL set and signing secret generated.</li>
          <li><strong>Send Test Webhook</strong> from the portal. Confirm your verifier accepts the signature.</li>
          <li>Sandbox run with <Code>sk_test_…</Code>, including a <Code>simulate_status: &quot;failed&quot;</Code> case.</li>
          <li>Optional: enable the IP allowlist and confirm a request still succeeds.</li>
          <li>One live push at the smallest workable amount, to a phone you control.</li>
          <li>
            Confirm the whole chain: <Code>202</Code> → webhook delivered → collection <Code>successful</Code> →
            merchant wallet credited.
          </li>
          <li>
            Confirm a deliberate failure — decline the prompt — arrives as <Code>collection.failed</Code> with{" "}
            <Code>failure_reason_code: &quot;user_cancelled&quot;</Code>.
          </li>
        </ol>
      </section>

      <DocsPager currentHref="/developers/direct-wallet-push" />
    </div>
  );
}
