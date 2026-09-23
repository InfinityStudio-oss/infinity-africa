import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  title: "API Key Authentication",
};

export default function AuthenticationPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Getting Started</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">API Key Authentication</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Every server-to-server call to InfinityPay is authenticated with an API key — a long-lived credential scoped to
        your account. There&apos;s no OAuth dance, no token refresh: generate a key once, send it on every
        request.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Two ways to authenticate</h2>
        <div className="space-y-4">
          <div className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl p-5">
            <h3 className="text-sm font-bold text-on-surface mb-1.5">API key — for your backend</h3>
            <p className="text-sm text-on-surface-variant leading-relaxed">
              Send <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">Authorization: Bearer &lt;INFINITY_API_KEY&gt;</code>{" "}
              (or the equivalent <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">X-API-Key: &lt;key&gt;</code> header)
              on any request originating from your own server (a website checkout, a mobile app&apos;s backend, an
              ecommerce platform&apos;s order webhook). This is what these docs cover.
            </p>
          </div>
          <div className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl p-5">
            <h3 className="text-sm font-bold text-on-surface mb-1.5">Dashboard session — for the InfinityPay portal only</h3>
            <p className="text-sm text-on-surface-variant leading-relaxed">
              The dashboard itself authenticates with a Supabase Auth session token, also sent as{" "}
              <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">Authorization: Bearer &lt;access_token&gt;</code> —
              InfinityPay tells the two apart by prefix, not by header. You won&apos;t use this in your own integration
              — it&apos;s only relevant if you&apos;re embedding the InfinityPay dashboard itself.
            </p>
          </div>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Generating a key</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Full API credentials are only ever generated inside the authenticated dashboard — sign in at{" "}
          <a href="/dashboard/login" className="text-primary font-semibold hover:underline">
            dashboard
          </a>
          , go to <strong>API Keys</strong>, choose <strong>Sandbox</strong> or <strong>Live</strong>, name the key,
          and check the scopes it needs (least privilege — a checkout integration only needs{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">collections:write</code>,
          for example). There is no public endpoint to generate a key — only{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">POST /v1/merchant/api-keys</code>,
          which requires a signed-in dashboard session:
        </p>
        <EndpointRow method="POST" path="/v1/merchant/api-keys" description="Create an API key for your own merchant — the plaintext key is shown once, in the response." auth="MERCHANT_ADMIN, DEVELOPER (dashboard session)" />
        <div className="mt-4 space-y-4">
          <CodeBlock language="json — request">{`{
  "name": "Production checkout server",
  "environment": "live",
  "scopes": ["collections:write", "payment_links:read"],
  "ip_whitelist_enabled": false,
  "continue_without_ip_whitelist": true
}`}</CodeBlock>
          <CodeBlock language="json — response">{`{
  "success": true,
  "data": {
    "id": "8f14e...",
    "name": "Production checkout server",
    "environment": "live",
    "key_prefix": "inf_live_9f2a1c3b",
    "key_last4": "d8e7",
    "scopes": ["collections:write", "payment_links:read"],
    "ip_whitelist_enabled": false,
    "continue_without_ip_whitelist": true,
    "plaintext_key": "inf_live_9f2a1c3bd8e7...",
    "status": "active",
    "created_at": "2026-08-14T09:00:00Z"
  }
}`}</CodeBlock>
        </div>
        <Callout tone="warning" title="Copy the plaintext key now — it won't be shown again">
          <code className="font-mono text-xs">plaintext_key</code> is only ever returned once, on creation. InfinityPay
          stores only a SHA-256 hash — never the plaintext, never a recoverable/encrypted form — so there is no
          &ldquo;reveal&rdquo; button anywhere, including for InfinityPay staff. If you lose a key, there&apos;s exactly one fix:
          rotate it (see below).
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Scopes</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Every key is issued with an explicit set of scopes — it can only call the endpoints those scopes cover. A
          request with a key missing the required scope gets a 403, not a partial success.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border border-outline-variant/40 rounded-xl overflow-hidden">
            <thead className="bg-surface-container-low">
              <tr>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Scope</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Grants</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {[
                ["collections:write", "Push USSD/STK/Selcom Pesa collections, generate Dynamic QR codes."],
                ["collections:read", "Read back collection status (dashboard-scoped listing)."],
                ["payment_links:write", "Create and cancel payment links."],
                ["payment_links:read", "Fetch a payment link by ID."],
                ["invoices:write", "Create, edit, send, and cancel invoices."],
                ["invoices:read", "Fetch an invoice by ID."],
                ["transactions:read", "Look up a transaction by reference."],
                ["webhooks:manage", "Configure the webhook URL, events, and secret."],
              ].map(([scope, grants]) => (
                <tr key={scope}>
                  <td className="px-4 py-2.5 font-mono text-xs text-on-surface">{scope}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant">{grants}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Sandbox vs. Live</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-3">
          Every key is scoped to an environment. Sandbox keys (prefix{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">inf_sandbox_...</code>) run
          against a fully simulated provider — nothing settles for real, so you can build and test your entire
          integration risk-free. Live keys (
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">inf_live_...</code>) move
          real money. Sandbox keys never expire on their own; both can be revoked at any time.
        </p>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          Both are self-service — creating a Sandbox key never requires approval. A Live key is also created directly
          from the dashboard, the moment your business account is approved, KYC-verified, and has pricing assigned;
          there is no separate &ldquo;request production access&rdquo; step or waiting on InfinityPay staff. Before that,
          creating a Live key returns:
        </p>
        <CodeBlock language="json — 403 response">{`{
  "success": false,
  "error": {
    "code": "production_access_restricted",
    "message": "Production API keys are available after your business account is approved."
  }
}`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Using your key</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-3">
          Attach it as a header on every request — never as a query parameter or in the request body, where it&apos;s
          more likely to end up logged somewhere:
        </p>
        <CodeBlock language="http">{`GET /v1/transactions/TXN-4821AB HTTP/1.1
Host: api.infinitypay.me
Authorization: Bearer inf_live_9f2a1c3bd8e7...`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">IP whitelisting (optional)</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-3">
          Every key makes a choice, at creation, between two options — there is no default forced on you:
        </p>
        <ul className="list-disc list-inside text-sm text-on-surface-variant leading-relaxed space-y-1.5 mb-3">
          <li>
            <strong className="text-on-surface">Continue without IP whitelisting</strong> (the default) — the key
            authenticates from any server IP. Simpler, and fine for most integrations.
          </li>
          <li>
            <strong className="text-on-surface">Enable IP whitelisting</strong> — requests only succeed from IPs you
            explicitly approve. Add them from the dashboard&apos;s <strong>IP Allowlist</strong> page (label, IP
            or CIDR, environment); each starts <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">pending</code> until
            a Super Admin approves it. A request from an unapproved IP gets a 403, and the attempt is logged.
          </li>
        </ul>
        <Callout title="Enforced for live traffic only">
          Sandbox requests are never IP-restricted, regardless of this setting — there&apos;s nothing real to protect
          there. For production, enabling IP whitelisting is recommended for stronger security, especially if your
          backend runs on a small, fixed set of server IPs.
        </Callout>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Revoking or rotating a key</h2>
        <EndpointRow method="PATCH" path="/v1/merchant/api-keys/{key_id}/revoke" description="Revoke a key immediately — any request using it afterward gets 401." auth="MERCHANT_ADMIN, DEVELOPER (dashboard session)" />
        <EndpointRow method="POST" path="/v1/merchant/api-keys/{key_id}/rotate" description="Revoke a key and create its replacement (same name/environment/scopes/IP-whitelist choice) in one call. The new plaintext key is returned once, same as creation." auth="MERCHANT_ADMIN, DEVELOPER (dashboard session)" />
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          Rotate keys periodically from the dashboard, revoke any key that may have leaked (committed to a
          public repo, shared in a support ticket, etc.) immediately rather than waiting for a scheduled rotation —
          and if you simply lose a key before copying it down, rotate is also how you recover: there is no way to
          view a key&apos;s secret again after creation, by design.
        </p>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Keep it secret, keep it server-side</h2>
        <Callout tone="warning" title="Never ship an API key to a browser, mobile app bundle, or public repo">
          A key embedded in client-side JavaScript, a mobile app binary, or committed source code can be extracted by
          anyone. Keep API keys on your server; have your website, ecommerce platform, or mobile app call your own
          backend, which then calls InfinityPay — never call InfinityPay directly from code that ships to a customer&apos;s
          device or browser.
        </Callout>
      </section>

      <DocsPager currentHref="/developers/authentication" />
    </div>
  );
}
