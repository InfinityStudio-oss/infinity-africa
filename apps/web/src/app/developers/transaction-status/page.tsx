import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  title: "Transaction Status API",
};

export default function TransactionStatusApiPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">API Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Transaction Status API</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Look up the settled status of any collection, withdrawal, fee, or refund by its human-readable reference —
        the fallback for when a webhook hasn&apos;t arrived yet, or you just want to confirm a result before
        continuing a flow.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Endpoint</h2>
        <div className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-5">
          <EndpointRow
            method="GET"
            path="/v1/transactions/{reference}"
            description="Look up a transaction by its reference (TXN-...)."
            auth="API key or dashboard"
          />
        </div>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Authentication</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Requires the <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">transactions:read</code> scope
          on the API key used. A key only ever sees transactions belonging to its own account.
        </p>
        <CodeBlock language="bash — cURL">{`curl https://api.infinitypay.me/v1/transactions/TXN-4821AB \\
  -H "Authorization: Bearer inf_live_xxxxxxxxxxxxx"`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Response</h2>
        <CodeBlock language="json — 200 OK">{`{
  "success": true,
  "data": {
    "id": "9b7e2c1a-...",
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "reference": "TXN-4821AB",
    "provider_reference": "MOCK-SELCOM-9F3A1C2B",
    "type": "collection",
    "method": "STK_PUSH",
    "collection_id": "2d4f8a91-...",
    "disbursement_id": null,
    "gross_amount": "25000.00",
    "fee_amount": "375.00",
    "net_amount": "24625.00",
    "currency": "TZS",
    "status": "successful",
    "created_at": "2026-08-14T09:00:12Z"
  }
}`}</CodeBlock>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Status values</h2>
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
                ["pending", "Created, not yet dispatched to a provider."],
                ["processing", "Awaiting customer or provider confirmation."],
                ["successful", "Settled — funds have moved."],
                ["failed", "Declined, expired, or errored — no funds moved."],
                ["reversed", "Settled, then reversed (e.g. a refund)."],
                ["cancelled", "Cancelled before settlement."],
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
        <h2 className="text-xl font-semibold text-on-surface mb-3">404 — reference not found</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          Returned for an unknown reference, or one belonging to a different account than your API key — the two
          cases are indistinguishable by design, so a key can never be used to probe for another account&apos;s
          transaction references.
        </p>
        <Callout title="Prefer webhooks for real-time updates">
          Polling this endpoint works, but{" "}
          <a href="/developers/webhooks" className="text-primary font-semibold hover:underline">
            Webhooks
          </a>{" "}
          push <code className="font-mono text-xs">collection.success</code> /{" "}
          <code className="font-mono text-xs">collection.failed</code> the moment a transaction settles — use this
          endpoint to confirm a specific reference on demand, not as your primary status feed.
        </Callout>
      </section>

      <DocsPager currentHref="/developers/transaction-status" />
    </div>
  );
}
