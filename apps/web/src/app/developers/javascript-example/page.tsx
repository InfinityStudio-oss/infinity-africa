import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";

export const metadata = {
  title: "JavaScript Example",
};

export default function JavaScriptExamplePage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Examples</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">JavaScript Example</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        A minimal Node.js client — no SDK, just <code className="font-mono text-sm bg-surface-container-low px-1.5 py-0.5 rounded">fetch</code>.
        Works the same from an Express/Next.js backend powering a website, an ecommerce checkout, or a mobile app&apos;s
        API layer.
      </p>

      <Callout title="Keep this code on your server">
        This example assumes it&apos;s running in a Node.js backend, not a browser — your API key must never reach
        client-side JavaScript. See{" "}
        <a href="/developers/authentication" className="text-primary font-semibold hover:underline">
          API Key Authentication
        </a>
        .
      </Callout>

      <section className="my-10">
        <h2 className="text-xl font-semibold text-on-surface mb-3">A small client wrapper</h2>
        <CodeBlock language="javascript — infinity-client.js">{`const BASE_URL = process.env.INFINITY_BASE_URL ?? "https://api.infinitypay.me";
const API_KEY = process.env.INFINITY_API_KEY;

async function infinityRequest(method, path, { body, idempotencyKey } = {}) {
  const headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
  };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  const response = await fetch(\`\${BASE_URL}\${path}\`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  const envelope = await response.json();
  if (!envelope.success) {
    const error = new Error(envelope.error.message);
    error.code = envelope.error.code;
    error.status = response.status;
    throw error;
  }
  return envelope.data;
}

module.exports = { infinityRequest };`}</CodeBlock>
      </section>

      <section className="mb-10">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Create a payment link at checkout</h2>
        <CodeBlock language="javascript">{`const { randomUUID } = require("crypto");
const { infinityRequest } = require("./infinity-client");

async function createCheckoutLink(order) {
  const link = await infinityRequest("POST", "/v1/payment-links", {
    idempotencyKey: randomUUID(),
    body: {
      merchant_id: process.env.INFINITY_MERCHANT_ID,
      amount: order.total.toFixed(2),
      currency: "TZS",
      customer_name: order.customerName,
      customer_phone: order.customerPhone,
      description: \`Order #\${order.id}\`,
      expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
    },
  });

  return link.public_url; // redirect your customer here
}`}</CodeBlock>
      </section>

      <section className="mb-10">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Handling errors</h2>
        <CodeBlock language="javascript">{`try {
  await createCheckoutLink(order);
} catch (err) {
  if (err.code === "insufficient_balance") {
    // won't happen for payment links, but this is the pattern for disbursements
  } else if (err.code === "validation_error") {
    console.error("Bad request:", err.message);
  } else {
    throw err; // let it bubble, retry, or alert — depending on your app
  }
}`}</CodeBlock>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Receiving webhooks (Express)</h2>
        <CodeBlock language="javascript">{`const express = require("express");
const crypto = require("crypto");

const app = express();

// Capture the raw body — signature verification needs the exact bytes,
// not JSON re-serialized after parsing.
app.post(
  "/webhooks/infinity",
  express.raw({ type: "application/json" }),
  (req, res) => {
    const signature = req.header("X-Infinity-Signature");
    const expected = crypto
      .createHmac("sha256", process.env.INFINITY_WEBHOOK_SECRET)
      .update(req.body)
      .digest("hex");

    if (signature !== expected) {
      return res.sendStatus(401);
    }

    const event = JSON.parse(req.body);
    switch (event.event_name) {
      case "collection.success":
        // mark the order as paid using event.payload.collection_id
        break;
      case "disbursement.failed":
        // alert someone — a payout didn't go through
        break;
    }

    res.sendStatus(200); // acknowledge fast; do heavy work asynchronously
  },
);`}</CodeBlock>
      </section>

      <DocsPager currentHref="/developers/javascript-example" />
    </div>
  );
}
