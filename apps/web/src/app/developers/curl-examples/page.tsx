import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";

export const metadata = {
  title: "cURL Examples",
};

export default function CurlExamplesPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Examples</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">cURL Examples</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Copy-pasteable requests for every core flow. Swap in your own API key, ID, and a fresh{" "}
        <code className="font-mono text-sm bg-surface-container-low px-1.5 py-0.5 rounded">Idempotency-Key</code> (a
        UUID) per attempt.
      </p>

      <section className="mb-10">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Create a payment link</h2>
        <CodeBlock language="bash">{`curl -X POST https://api.infinitypay.me/v1/payment-links \\
  -H "X-API-Key: $INFINITY_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: $(uuidgen)" \\
  -d '{
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "amount": "25000.00",
    "currency": "TZS",
    "description": "Web design deposit"
  }'`}</CodeBlock>
      </section>

      <section className="mb-10">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Push an STK collection</h2>
        <CodeBlock language="bash">{`curl -X POST https://api.infinitypay.me/v1/collections/stk-push \\
  -H "X-API-Key: $INFINITY_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: $(uuidgen)" \\
  -d '{
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "amount": "25000.00",
    "customer_phone": "255712345678",
    "merchant_reference": "ORDER-4821"
  }'`}</CodeBlock>
      </section>

      <section className="mb-10">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Create and send an invoice</h2>
        <CodeBlock language="bash">{`curl -X POST https://api.infinitypay.me/v1/invoices \\
  -H "X-API-Key: $INFINITY_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "merchant_id": "5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
    "customer_name": "Juma Traders Ltd",
    "customer_phone": "255712445310",
    "due_date": "2026-09-01",
    "items": [
      { "description": "Wholesale delivery", "quantity": "1", "unit_price": "320000.00" }
    ]
  }'

# Grab "id" from the response, then:
curl -X POST https://api.infinitypay.me/v1/invoices/INVOICE_ID/send \\
  -H "X-API-Key: $INFINITY_API_KEY"

curl -X POST https://api.infinitypay.me/v1/invoices/INVOICE_ID/payment-link \\
  -H "X-API-Key: $INFINITY_API_KEY"`}</CodeBlock>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">List recent transactions</h2>
        <CodeBlock language="bash">{`curl "https://api.infinitypay.me/v1/merchants/5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71/transactions?page=1&page_size=20" \\
  -H "X-API-Key: $INFINITY_API_KEY"`}</CodeBlock>
      </section>

      <DocsPager currentHref="/developers/curl-examples" />
    </div>
  );
}
