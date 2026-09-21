import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";

export const metadata = {
  title: "Python Example",
};

export default function PythonExamplePage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Examples</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Python Example</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        A minimal client using <code className="font-mono text-sm bg-surface-container-low px-1.5 py-0.5 rounded">requests</code>.
        Suits a Django/Flask/FastAPI backend behind a website, an ecommerce platform, or a mobile app&apos;s API.
      </p>

      <Callout title="Keep this code on your server">
        As with any language, your API key belongs in a backend environment variable — never in code shipped to a
        browser or mobile app bundle. See{" "}
        <a href="/developers/authentication" className="text-primary font-semibold hover:underline">
          API Key Authentication
        </a>
        .
      </Callout>

      <section className="my-10">
        <h2 className="text-xl font-semibold text-on-surface mb-3">A small client wrapper</h2>
        <CodeBlock language="python — infinity_client.py">{`import os
import requests

BASE_URL = os.environ.get("INFINITY_BASE_URL", "https://api.infinitypay.me")
API_KEY = os.environ["INFINITY_API_KEY"]


class InfinityAPIError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def infinity_request(method: str, path: str, *, body: dict | None = None, idempotency_key: str | None = None) -> dict:
    headers = {"X-API-Key": API_KEY}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    response = requests.request(method, f"{BASE_URL}{path}", json=body, headers=headers, timeout=30)
    envelope = response.json()

    if not envelope["success"]:
        raise InfinityAPIError(envelope["error"]["code"], envelope["error"]["message"], response.status_code)

    return envelope["data"]`}</CodeBlock>
      </section>

      <section className="mb-10">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Push a collection</h2>
        <CodeBlock language="python">{`import uuid

from infinity_client import infinity_request, InfinityAPIError

def collect_from_customer(merchant_id: str, phone: str, amount: str, reference: str) -> dict:
    return infinity_request(
        "POST",
        "/v1/collections/stk-push",
        idempotency_key=str(uuid.uuid4()),
        body={
            "merchant_id": merchant_id,
            "amount": amount,
            "customer_phone": phone,
            "merchant_reference": reference,
        },
    )

try:
    collection = collect_from_customer(
        merchant_id="5c1f0b2a-3e21-4b9a-9c33-2f6a1d0e8b71",
        phone="+255712345678",
        amount="25000.00",
        reference="ORDER-4821",
    )
    print(collection["status"])  # "processing" — resolves via webhook
except InfinityAPIError as exc:
    print(f"InfinityPay error [{exc.code}]: {exc}")`}</CodeBlock>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Receiving webhooks (Flask)</h2>
        <CodeBlock language="python">{`import hashlib
import hmac
import os

from flask import Flask, request, abort

app = Flask(__name__)
WEBHOOK_SECRET = os.environ["INFINITY_WEBHOOK_SECRET"]


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhooks/infinity")
def handle_webhook():
    raw_body = request.get_data()  # exact bytes — read before touching request.json
    signature = request.headers.get("X-Infinity-Signature")

    if not verify_signature(raw_body, signature):
        abort(401)

    event = request.get_json()
    if event["event_name"] == "invoice.paid":
        mark_invoice_paid(event["payload"]["invoice_id"])
    elif event["event_name"] == "disbursement.failed":
        alert_ops_team(event["payload"])

    return "", 200  # acknowledge fast; do heavy work in a background task`}</CodeBlock>
      </section>

      <DocsPager currentHref="/developers/python-example" />
    </div>
  );
}
