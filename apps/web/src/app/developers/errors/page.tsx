import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";

export const metadata = {
  title: "Error Codes",
};

const ERRORS: Array<{ status: number; code: string; meaning: string }> = [
  { status: 400, code: "bad_request", meaning: "A generic request problem that doesn't fit a more specific code." },
  { status: 401, code: "unauthorized", meaning: "Missing or invalid credentials — no X-API-Key/Bearer token, or the key was revoked." },
  { status: 403, code: "forbidden", meaning: "Your credentials are valid, but not authorized for this merchant or resource." },
  { status: 404, code: "not_found", meaning: "The resource doesn't exist, or doesn't belong to your merchant." },
  { status: 409, code: "conflict", meaning: "The request conflicts with the resource's current state (e.g. cancelling an already-paid link)." },
  { status: 409, code: "idempotency_key_reused", meaning: "The same Idempotency-Key was sent with a different request body." },
  { status: 409, code: "insufficient_balance", meaning: "A disbursement amount exceeds your current available balance." },
  { status: 422, code: "validation_error", meaning: "The request body failed validation — see error.details for the field-level breakdown." },
  { status: 500, code: "internal_error", meaning: "Something went wrong on InfinityPay's side. Safe to retry; contact us if it persists." },
];

export default function ErrorCodesPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Error Codes</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Every error response has the same shape — an HTTP status code, plus a stable machine-readable{" "}
        <code className="font-mono text-sm bg-surface-container-low px-1.5 py-0.5 rounded">error.code</code> you can
        branch your own logic on without parsing the human-readable message.
      </p>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Error shape</h2>
        <CodeBlock language="json">{`{
  "success": false,
  "error": {
    "code": "validation_error",
    "message": "Invalid request",
    "details": [
      { "loc": ["body", "amount"], "msg": "Input should be greater than 0", "type": "greater_than" }
    ]
  }
}`}</CodeBlock>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-3">
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">details</code> is{" "}
          <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">null</code> for most error
          codes — it&apos;s only populated for <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">validation_error</code>,
          where it&apos;s the field-by-field list of what failed.
        </p>
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Codes</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border border-outline-variant/40 rounded-xl overflow-hidden">
            <thead className="bg-surface-container-low">
              <tr>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">HTTP Status</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">error.code</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Meaning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {ERRORS.map((error) => (
                <tr key={error.code}>
                  <td className="px-4 py-2.5 font-mono text-xs text-on-surface">{error.status}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-on-surface">{error.code}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant">{error.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Handling errors safely</h2>
        <ul className="space-y-3 text-sm text-on-surface-variant leading-relaxed list-disc list-inside">
          <li>
            Branch on <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">error.code</code>,
            never on <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">error.message</code> —
            the message text may change; the code won&apos;t.
          </li>
          <li>
            A <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">409 idempotency_key_reused</code> almost
            always means a bug in your retry logic (reusing a key across two different requests) — it&apos;s not
            something to retry.
          </li>
          <li>
            <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">500 internal_error</code> is
            safe to retry with the same idempotency key; everything else reflects something about the request itself
            that a retry won&apos;t fix.
          </li>
        </ul>
      </section>

      <DocsPager currentHref="/developers/errors" />
    </div>
  );
}
