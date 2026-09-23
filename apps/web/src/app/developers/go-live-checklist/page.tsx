import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";

export const metadata = {
  title: "Go-Live Checklist",
};

function Code({ children }: { children: React.ReactNode }) {
  return <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">{children}</code>;
}

const CHECKLIST: Array<{ title: string; items: string[] }> = [
  {
    title: "Credentials",
    items: [
      "Generate a live API key from the dashboard (API Keys → Live) with only the scopes your integration actually uses.",
      "Store the key in your backend's secret manager or environment variables — never in a repo, a mobile app bundle, or any frontend/client-side code.",
      "Set a webhook secret (dashboard → Webhooks, or PATCH /v1/merchant/webhook-config with regenerate_secret) and store it the same way.",
    ],
  },
  {
    title: "Integration",
    items: [
      "Every write request sends a fresh Idempotency-Key per genuine user action (not per HTTP retry of the same action).",
      "Your order-paid logic only triggers on collection.successful (webhook) or status: \"successful\" from GET /v1/collections/{id} — never on created, processing, pending_clearance, a QR/token being returned, or a push's initial resultcode.",
      "Your webhook endpoint verifies X-Infinity-Signature on every delivery before trusting the payload.",
      "Your webhook handler responds quickly (do slow processing asynchronously) and treats deliveries as idempotent — keyed off collection_id.",
      "You've tested Send Test Webhook from the dashboard against your real endpoint.",
      "You handle collection.failed, collection.reversed, and collection.pending_review distinctly from collection.successful in your own order state — a reversal after credit is a real scenario, not an edge case to ignore.",
    ],
  },
  {
    title: "Selcom account",
    items: [
      "Confirm with Selcom which of Mobile Money Push / Selcom Pesa / Scan QR your account is actually provisioned for — Hosted Checkout is currently inactive platform-wide (see below), don't build against it.",
      "Test with a small real amount on a phone/account you control before sending real customer traffic.",
    ],
  },
  {
    title: "Compliance & security",
    items: [
      "Account KYC/onboarding is approved (see Onboarding Requirements).",
      "HTTPS only — for your webhook endpoint and everywhere you call the InfinityPay API from.",
      "No InfinityPay or Selcom credential appears in any frontend bundle, mobile app package, or public repository.",
    ],
  },
];

export default function GoLiveChecklistPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Go-Live Checklist</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Work through this before sending real customer traffic through a live API key. Every item here maps to a
        specific incident this platform has actually had — this isn&apos;t generic advice.
      </p>

      <section className="mb-12 space-y-8">
        {CHECKLIST.map((group) => (
          <div key={group.title}>
            <h2 className="text-xl font-semibold text-on-surface mb-3">{group.title}</h2>
            <ul className="space-y-2">
              {group.items.map((item) => (
                <li key={item} className="flex items-start gap-2.5 text-sm text-on-surface-variant leading-relaxed">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Security best practices</h2>
        <div className="space-y-4">
          <Callout tone="warning" title="Never ship a secret key to anywhere a customer's device can read it">
            An API key or webhook secret in a browser bundle, a mobile app package, or a public repository can be
            extracted by anyone. Keep both server-side; have client apps call your own backend, and have your
            backend call InfinityPay.
          </Callout>
          <p className="text-sm text-on-surface-variant leading-relaxed">
            A few more that matter in practice:
          </p>
          <ul className="space-y-2">
            {[
              "Rotate a key immediately if you suspect it leaked — Rotate on the API Keys page revokes the old one and issues a replacement with the same scopes in one action.",
              "Scope each key to only what it needs (collections:write for a checkout server doesn't need transactions:read).",
              "Verify every webhook signature — an unsigned or wrong-secret delivery should be rejected, not processed.",
              "Log request IDs / collection IDs, not full request/response bodies, if your logs might ever be shared for support — avoid retaining customer phone numbers longer than you need to.",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2.5 text-sm text-on-surface-variant leading-relaxed">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Hosted Checkout is not available</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          Selcom&apos;s hosted checkout redirect (<Code>payment_gateway_url</Code>) is currently inactive
          platform-wide — it returned &quot;Page Not Found&quot; for every order tested. Don&apos;t build an
          integration that redirects a customer there. Use the{" "}
          <a href="/developers/collections" className="text-primary font-semibold hover:underline">
            Infinity Payment Page flow
          </a>{" "}
          instead — it offers the same &quot;you don&apos;t pick a channel&quot; experience via Infinity&apos;s own
          page, backed by the three active methods (Mobile Money Push, Selcom Pesa, Scan QR / TanQR).
        </p>
      </section>

      <DocsPager currentHref="/developers/go-live-checklist" />
    </div>
  );
}
