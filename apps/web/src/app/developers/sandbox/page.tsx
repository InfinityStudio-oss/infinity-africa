import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";

export const metadata = {
  title: "Sandbox Examples",
};

export default function SandboxPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Examples</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Sandbox Examples</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Every sandbox request runs against a mock payment network — no real money moves, no real SMS is sent, and
        nothing settles. Build and test your entire integration before switching to a live key.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Getting a sandbox key</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed">
          Generate one from the dashboard&apos;s API Keys page (choose the <strong>Sandbox</strong> tab), or via{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">POST /v1/merchants/{"{id}"}/api-keys</code> with{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">&quot;environment&quot;: &quot;sandbox&quot;</code> — see{" "}
          <a href="/developers/authentication" className="text-primary font-semibold hover:underline">
            API Key Authentication
          </a>
          .
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">How sandbox collections behave</h2>
        <p className="text-sm text-on-surface-variant leading-relaxed mb-4">
          A sandbox key routes{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">
            POST /v1/collections/{"{wallet-push,selcom-pesa,qr}"}
          </code>{" "}
          to a fully simulated flow — Selcom is never called, and nothing ever touches a real wallet balance. The
          collection resolves to <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">successful</code> immediately
          by default. Pass <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">simulate_status</code> to
          test a different outcome:
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border border-outline-variant/40 rounded-xl overflow-hidden">
            <thead className="bg-surface-container-low">
              <tr>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">simulate_status</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              <tr>
                <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">successful (default)</td>
                <td className="px-4 py-2.5 text-on-surface">Collection resolves as paid</td>
              </tr>
              <tr>
                <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">failed</td>
                <td className="px-4 py-2.5 text-on-surface">Collection resolves as failed</td>
              </tr>
              <tr>
                <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">pending_clearance</td>
                <td className="px-4 py-2.5 text-on-surface">Held for manual clearance, same as a real self-payment/risk hold</td>
              </tr>
              <tr>
                <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">reversed</td>
                <td className="px-4 py-2.5 text-on-surface">Resolves as a settled-then-reversed payment</td>
              </tr>
            </tbody>
          </table>
        </div>
        <CodeBlock language="bash">{`curl -X POST https://api.infinitypay.me/v1/collections/wallet-push \\
  -H "Authorization: Bearer $INFINITY_SANDBOX_KEY" \\
  -H "Idempotency-Key: $(uuidgen)" \\
  -H "Content-Type: application/json" \\
  -d '{"merchant_id":"...","amount":1000,"phone":"255700000000","simulate_status":"failed"}'`}</CodeBlock>
        <Callout title="simulate_status is sandbox-only">
          Sending it with a <code className="font-mono text-xs">live</code> key is rejected outright (
          <code className="font-mono text-xs">422</code>) — it never silently does nothing.
        </Callout>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          One boundary worth knowing: this simulation only covers the three direct push/QR endpoints above — the
          &quot;Infinity Payment Page&quot; flow (<code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">POST /v1/collections</code>,
          the customer-facing checkout page) is not sandbox-aware yet and always runs the real flow regardless of
          which key created it.
        </p>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">A full sandbox test flow</h2>
        <ol className="space-y-3 text-sm text-on-surface-variant leading-relaxed list-decimal list-inside">
          <li>Generate a sandbox key and set it as your X-API-Key.</li>
          <li>
            Create a payment link (<code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">POST /v1/payment-links</code>)
            and open <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">public_url</code> in
            a browser.
          </li>
          <li>Complete checkout — the mock provider resolves it within the same request, roughly 90% of the time successfully.</li>
          <li>
            Check <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">GET /v1/merchants/{"{id}"}/transactions</code> and
            confirm a ledger entry appeared.
          </li>
          <li>Request a small disbursement and watch it resolve to SUCCESS or FAILED.</li>
          <li>Point your webhook_url at a local tunnel (e.g. ngrok) and confirm delivery of the resulting events.</li>
        </ol>
      </section>

      <DocsPager currentHref="/developers/sandbox" />
    </div>
  );
}
