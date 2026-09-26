import Link from "next/link";

import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { Icon } from "@/components/portal/icon";

export const metadata = {
  title: "REST API Overview",
};

const RESOURCES = [
  { icon: "payments", title: "Collections API", description: "Push USSD, STK Push, Selcom Pesa Push, and Dynamic QR collections.", href: "/developers/collections" },
  { icon: "link", title: "Payment Links API", description: "Generate shareable checkout links for any amount.", href: "/developers/payment-links" },
  { icon: "receipt_long", title: "Invoices API", description: "Itemized invoices with a built-in Pay Now link.", href: "/developers/invoices" },
  { icon: "webhook", title: "Webhooks", description: "Real-time event notifications delivered to your server.", href: "/developers/webhooks" },
  { icon: "error", title: "Error Codes", description: "Every error code the API returns, and what to do about it.", href: "/developers/errors" },
];

export default function DocsOverviewPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Getting Started</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">REST API Overview</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        The InfinityPay API lets you accept mobile money collections, generate payment links and invoices, and send
        disbursements — from a website, a mobile app, an ecommerce platform, or your own backend. It&apos;s a
        predictable, versioned REST API: JSON in, JSON out, one response shape everywhere.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Base URL</h2>
        <p className="text-sm text-on-surface-variant mb-3">
          Every endpoint in these docs is relative to your environment&apos;s base URL:
        </p>
        <CodeBlock language="text">{`Production   https://api.infinitypay.me
Sandbox      https://sandbox.infinitypay.me
Local dev    http://localhost:8000`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">The response envelope</h2>
        <p className="text-sm text-on-surface-variant mb-3">
          Every response — success or error, single object or paginated list — has the same top-level shape, so you
          only need to write one response parser:
        </p>
        <div className="space-y-4">
          <CodeBlock language="json — success">{`{
  "success": true,
  "data": { "...": "..." },
  "meta": null
}`}</CodeBlock>
          <CodeBlock language="json — paginated list">{`{
  "success": true,
  "data": [ { "...": "..." } ],
  "meta": { "page": 1, "page_size": 20, "total": 42, "total_pages": 3 }
}`}</CodeBlock>
          <CodeBlock language="json — error">{`{
  "success": false,
  "error": {
    "code": "insufficient_balance",
    "message": "Insufficient balance: available TZS 100,000, requested TZS 5,000,000",
    "details": null
  }
}`}</CodeBlock>
        </div>
        <p className="text-sm text-on-surface-variant mt-3">
          List endpoints accept <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">?page=1&amp;page_size=20</code> (
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">page_size</code> caps at 100). See{" "}
          <Link href="/developers/errors" className="text-primary font-semibold hover:underline">
            Error Codes
          </Link>{" "}
          for the full list of <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">error.code</code> values.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Authentication</h2>
        <p className="text-sm text-on-surface-variant mb-4">
          Server-to-server requests — from your backend, not a browser — authenticate with an API key generated in
          the dashboard, sent as an{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">Authorization: Bearer</code> header
          (or the equivalent <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">X-API-Key</code> header).
          Use the <strong>secret</strong> half of the key pair — the public key identifies a key but cannot
          authorize a request. Full detail, including scopes, sandbox vs. live keys, and key rotation, is in{" "}
          <Link href="/developers/authentication" className="text-primary font-semibold hover:underline">
            API Key Authentication
          </Link>
          .
        </p>
        <CodeBlock language="http">{`Authorization: Bearer sk_live_YOUR_SECRET_KEY`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Idempotency</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-3">
          Every endpoint that moves money — creating a payment link, initiating a collection, requesting a
          disbursement, or a customer completing a checkout — requires an{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">Idempotency-Key</code>{" "}
          header (any unique string, e.g. a UUID you generate per attempt). Retrying the same key with the same
          request body replays the original response instead of double-processing; reusing the key with a{" "}
          <em>different</em> body is rejected with <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">409 idempotency_key_reused</code>.
        </p>
        <Callout title="Always generate a fresh key per user action, not per HTTP request">
          If your client retries a failed request automatically (a timeout, a dropped connection), reuse the same
          idempotency key for those retries — that&apos;s exactly the safety net it&apos;s for. Generate a new key
          only when the customer initiates a genuinely new payment.
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">API resources</h2>
        <div className="grid sm:grid-cols-2 gap-4">
          {RESOURCES.map((resource) => (
            <Link
              key={resource.href}
              href={resource.href}
              className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl p-5 shadow-ambient hover:shadow-ambient-lg hover:-translate-y-0.5 transition-all duration-200"
            >
              <div className="w-10 h-10 rounded-lg bg-primary-container/10 flex items-center justify-center mb-3">
                <Icon name={resource.icon} className="text-primary-container text-[22px]" />
              </div>
              <h3 className="text-sm font-bold text-on-surface mb-1">{resource.title}</h3>
              <p className="text-sm text-on-surface-variant leading-relaxed">{resource.description}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Rate limits</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          Each API key is limited to 120 requests per minute by default. Responses include no special
          rate-limit headers yet — if you need a higher limit for a high-volume integration,{" "}
          <Link href="/#contact" className="text-primary font-semibold hover:underline">
            contact us
          </Link>
          .
        </p>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Who this API is for</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          The same REST API powers every kind of integration — a checkout flow on a website, a native mobile app, an
          ecommerce plugin, or an internal web app calling InfinityPay from your own backend. There&apos;s no
          platform-specific SDK required: any language or framework that can make an HTTPS request and parse JSON can
          integrate. See{" "}
          <Link href="/developers/curl-examples" className="text-primary font-semibold hover:underline">
            cURL
          </Link>
          ,{" "}
          <Link href="/developers/javascript-example" className="text-primary font-semibold hover:underline">
            JavaScript
          </Link>
          , and{" "}
          <Link href="/developers/python-example" className="text-primary font-semibold hover:underline">
            Python
          </Link>{" "}
          examples to get started in your stack.
        </p>
      </section>

      <DocsPager currentHref="/developers" />
    </div>
  );
}
