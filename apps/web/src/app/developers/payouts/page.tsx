import { Callout } from "@/components/docs/callout";
import { CodeBlock } from "@/components/docs/code-block";
import { DocsPager } from "@/components/docs/docs-pager";
import { EndpointRow } from "@/components/docs/endpoint-row";

export const metadata = {
  alternates: { canonical: "/developers/payouts" },
  title: "Payouts API — Disbursement API",
  description:
    "Send money out from a prefunded payout wallet: payout keys, approved beneficiaries, creating a payout, the status lifecycle, idempotency, limits and fees.",
};

function Code({ children }: { children: React.ReactNode }) {
  return <code className="font-mono text-xs bg-surface-container-low px-1.5 py-0.5 rounded">{children}</code>;
}

const REQUEST_FIELDS: Array<{ field: string; required: string; notes: React.ReactNode }> = [
  {
    field: "beneficiary_id",
    required: "Yes",
    notes: (
      <>
        An approved destination. A payout names a beneficiary, never a raw phone number — see{" "}
        <a href="#beneficiaries" className="text-primary hover:underline">
          Beneficiaries
        </a>
        .
      </>
    ),
  },
  {
    field: "amount",
    required: "Yes",
    notes: (
      <>
        Decimal string, e.g. <Code>&quot;1000.00&quot;</Code>, at most 2 decimal places.{" "}
        <strong>Exclusive of the fee</strong> — the fee is added on top and debited with it.
      </>
    ),
  },
  { field: "currency", required: "No", notes: <>Defaults to <Code>TZS</Code>.</> },
  {
    field: "metadata",
    required: "No",
    notes: (
      <>
        Up to 20 keys. Values must be a string, number, boolean or null; strings up to 500
        characters. Echoed back on reads.
      </>
    ),
  },
];

const STATUSES: Array<{ status: string; money: string; action: string }> = [
  {
    status: "queued",
    money: "Accepted. Nothing reserved yet.",
    action: "Wait.",
  },
  {
    status: "processing",
    money: "Funds reserved and committed to this payout.",
    action: "Wait. Do not retry.",
  },
  {
    status: "needs_reconciliation",
    money: "Outcome unknown. Funds are STILL HELD.",
    action: "Wait. We keep asking the provider. Never treat this as a failure.",
  },
  {
    status: "successful",
    money: "Confirmed paid. Reserve released to the provider and the fee taken.",
    action: "Done.",
  },
  { status: "failed", money: "Confirmed not paid. Reserve returned to your wallet.", action: "Read failure_code." },
  {
    status: "cancelled",
    money: "Confirmed never sent. Reserve returned.",
    action: "Read failure_code — a limit or funds refusal lands here.",
  },
  {
    status: "reversed",
    money: "Reversed after succeeding. A compensating entry; the original stays as it was.",
    action: "Reverse whatever you did on success.",
  },
];

const FAILURES: Array<{ code: string; meaning: string }> = [
  { code: "insufficient_funds", meaning: "The payout wallet could not cover the amount plus fee." },
  { code: "daily_limit_exceeded", meaning: "Would exceed the account's rolling 24-hour limit." },
  { code: "provider_unreachable", meaning: "The request did not complete. Outcome unknown, funds held." },
  { code: "beneficiary_missing", meaning: "The beneficiary could not be read. Funds held." },
];

export default function PayoutsApiPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">API Reference</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Payouts API</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-10 max-w-2xl">
        Send money out from a payout wallet you fund in advance. Your server calls this directly —
        nobody approves each request — so the wallet balance is the ceiling on what the API can
        ever cost you.
      </p>

      <Callout tone="warning" title="This API moves money out without a person">
        Read{" "}
        <a href="#what-caps-it" className="underline">
          What caps it
        </a>{" "}
        before you integrate. Access is granted per account and per environment — contact
        InfinityPay support to start in the sandbox.
      </Callout>

      {/* --- model ----------------------------------------------------- */}

      <h2 className="text-2xl font-bold text-on-surface mt-12 mb-4">How it works</h2>
      <ol className="list-decimal pl-5 space-y-2 text-on-surface-variant mb-6 max-w-2xl">
        <li>
          Your account is given payout access for an environment, and you create a{" "}
          <strong>payout key</strong> in the dashboard.
        </li>
        <li>
          You move money from your Collections balance into the <strong>payout wallet</strong>. This
          is a dashboard action behind two-factor authentication.
        </li>
        <li>
          Destinations are approved in advance as <strong>beneficiaries</strong>.
        </li>
        <li>
          Your server calls <Code>POST /v1/payouts</Code> naming a beneficiary and an amount.
        </li>
        <li>We send it, and the payout reaches a terminal status you can poll for.</li>
      </ol>

      <h2 id="what-caps-it" className="text-2xl font-bold text-on-surface mt-12 mb-4">
        What caps it
      </h2>
      <p className="text-on-surface-variant mb-4 max-w-2xl">
        A leaked payout key is the thing this design is built around. Three limits apply, and none
        of them can be raised by the key itself:
      </p>
      <ul className="list-disc pl-5 space-y-2 text-on-surface-variant mb-6 max-w-2xl">
        <li>
          <strong>The wallet balance.</strong> A payout key spends only what is already in the
          payout wallet. It <strong>cannot</strong> top that wallet up — funding is a dashboard
          action behind your own second factor. Keep the wallet at what you are willing to lose.
        </li>
        <li>
          <strong>The beneficiary list.</strong> A payout names a <Code>beneficiary_id</Code>. A key
          cannot invent a destination, so the worst case is money sent to someone already approved.
        </li>
        <li>
          <strong>Per-payout and rolling 24-hour limits</strong>, if set on your account.
        </li>
      </ul>
      <Callout tone="info" title="What a payout key cannot do">
        A payout key cannot reach your Collections balance, cannot request a withdrawal, and cannot
        create collections. It carries <Code>payouts:create</Code> and <Code>payouts:read</Code>{" "}
        and nothing else.
      </Callout>

      {/* --- auth ------------------------------------------------------ */}

      <h2 className="text-2xl font-bold text-on-surface mt-12 mb-4">Authentication</h2>
      <p className="text-on-surface-variant mb-4 max-w-2xl">
        A payout key, as a bearer token. It is a different key from your collections API key and is
        created on its own tab in the dashboard.
      </p>
      <CodeBlock language="bash">{`curl https://api.infinitypay.me/v1/payouts \\
  -H "Authorization: Bearer sk_test_your_payout_key"`}</CodeBlock>
      <p className="text-on-surface-variant mt-4 mb-6 max-w-2xl">
        Sandbox keys are <Code>sk_test_…</Code> and live keys <Code>sk_live_…</Code>. The key
        decides the environment; there is no environment field on the request.
      </p>

      {/* --- beneficiaries --------------------------------------------- */}

      <h2 id="beneficiaries" className="text-2xl font-bold text-on-surface mt-12 mb-4">
        Beneficiaries
      </h2>
      <p className="text-on-surface-variant mb-4 max-w-2xl">
        Every payout goes to a beneficiary approved beforehand. A beneficiary belongs to one
        environment: a sandbox beneficiary cannot receive a live payout.
      </p>
      <Callout tone="warning" title="No self-service beneficiaries yet">
        During the pilot,
        destinations are added for you — send InfinityPay support the name, network and number, and
        you will get back a <Code>beneficiary_id</Code>. This page will be updated when
        self-service arrives.
      </Callout>
      <p className="text-on-surface-variant mt-4 mb-6 max-w-2xl">
        Asking for a beneficiary that does not exist, belongs to another account, is in the other
        environment, or has been disabled all return the same <Code>404</Code>. That is deliberate —
        a different answer for each would let a key probe for other businesses&apos; destinations.
      </p>

      {/* --- create ---------------------------------------------------- */}

      <h2 className="text-2xl font-bold text-on-surface mt-12 mb-4">Create a payout</h2>
      <EndpointRow method="POST" path="/v1/payouts" description="Send one payout to an approved beneficiary." auth="Payout key" />

      <p className="text-on-surface-variant mt-6 mb-3 max-w-2xl">
        <Code>Idempotency-Key</Code> is a <strong>required header</strong>. Reuse the same key when
        retrying and you will get the original payout back rather than a second payment.
      </p>

      <CodeBlock language="bash">{`curl -X POST https://api.infinitypay.me/v1/payouts \\
  -H "Authorization: Bearer sk_test_your_payout_key" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: payout-2026-11-21-0001" \\
  -d '{
    "beneficiary_id": "05104c2f-9261-48e5-82a8-f6f37fa825f0",
    "amount": "1000.00",
    "currency": "TZS"
  }'`}</CodeBlock>

      <h3 className="text-lg font-semibold text-on-surface mt-8 mb-3">Request fields</h3>
      <div className="overflow-x-auto mb-8">
        <table className="w-full text-left text-sm min-w-[620px]">
          <thead>
            <tr className="text-on-surface-variant text-xs font-semibold border-b border-outline-variant">
              <th className="py-2 pr-4">Field</th>
              <th className="py-2 pr-4">Required</th>
              <th className="py-2">Notes</th>
            </tr>
          </thead>
          <tbody>
            {REQUEST_FIELDS.map((row) => (
              <tr key={row.field} className="border-b border-surface-container-highest align-top">
                <td className="py-2.5 pr-4 font-mono text-xs text-on-surface">{row.field}</td>
                <td className="py-2.5 pr-4 text-on-surface-variant">{row.required}</td>
                <td className="py-2.5 text-on-surface-variant">{row.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-on-surface-variant mb-3 max-w-2xl">
        Unknown fields are <strong>refused</strong>, not ignored. Sending <Code>merchant_id</Code>{" "}
        is the case that matters: silently dropping it and returning 201 would let you believe you
        had aimed the payout somewhere you had not.
      </p>

      <h3 className="text-lg font-semibold text-on-surface mt-8 mb-3">Response</h3>
      <CodeBlock language="json">{`{
  "success": true,
  "data": {
    "id": "81a04fe6-8c70-4095-81a7-88e85b6fad9b",
    "status": "processing",
    "amount": "1000.0",
    "fee_amount": "10.0",
    "total_debit": "1010.0",
    "currency": "TZS",
    "environment": "sandbox",
    "beneficiary_id": "05104c2f-9261-48e5-82a8-f6f37fa825f0",
    "reference": "PO-3D20F0D34650447AA096",
    "failure_code": null,
    "failure_reason": null,
    "created_at": "2026-11-21T21:37:00.345948Z",
    "completed_at": null
  }
}`}</CodeBlock>
      <p className="text-on-surface-variant mt-4 mb-6 max-w-2xl">
        <Code>total_debit</Code> is what leaves your wallet: the amount plus the fee. It is stored
        on the payout, so a later change to your pricing never re-prices a payout already made.
      </p>

      {/* --- read ------------------------------------------------------ */}

      <h2 className="text-2xl font-bold text-on-surface mt-12 mb-4">Read payouts</h2>
      <EndpointRow method="GET" path="/v1/payouts" description="List your payouts, newest first." auth="Payout key" />
      <div className="mt-3">
        <EndpointRow method="GET" path="/v1/payouts/{payout_id}" description="Fetch one payout and its current status." auth="Payout key" />
      </div>
      <p className="text-on-surface-variant mt-6 mb-6 max-w-2xl">
        The list is paginated and newest first. Both are scoped to your account and your key&apos;s
        environment.
      </p>

      {/* --- lifecycle ------------------------------------------------- */}

      <h2 className="text-2xl font-bold text-on-surface mt-12 mb-4">Status lifecycle</h2>
      <p className="text-on-surface-variant mb-4 max-w-2xl">
        Each status is named for what is true about <strong>the money</strong>, not about our
        processing.
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-left text-sm min-w-[720px]">
          <thead>
            <tr className="text-on-surface-variant text-xs font-semibold border-b border-outline-variant">
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">What is true of the money</th>
              <th className="py-2">What you should do</th>
            </tr>
          </thead>
          <tbody>
            {STATUSES.map((row) => (
              <tr key={row.status} className="border-b border-surface-container-highest align-top">
                <td className="py-2.5 pr-4 font-mono text-xs text-on-surface">{row.status}</td>
                <td className="py-2.5 pr-4 text-on-surface-variant">{row.money}</td>
                <td className="py-2.5 text-on-surface-variant">{row.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout tone="warning" title="needs_reconciliation is not a failure">
        It means we asked the provider and did not get a usable answer — a timeout, a dropped
        connection. The money stays reserved and we keep asking, because releasing funds on a slow
        response is exactly how a payout gets paid twice. Do not retry it and do not refund against
        it.
      </Callout>

      <h3 className="text-lg font-semibold text-on-surface mt-8 mb-3">Failure codes</h3>
      <div className="overflow-x-auto mb-8">
        <table className="w-full text-left text-sm min-w-[560px]">
          <thead>
            <tr className="text-on-surface-variant text-xs font-semibold border-b border-outline-variant">
              <th className="py-2 pr-4">Code</th>
              <th className="py-2">Meaning</th>
            </tr>
          </thead>
          <tbody>
            {FAILURES.map((row) => (
              <tr key={row.code} className="border-b border-surface-container-highest align-top">
                <td className="py-2.5 pr-4 font-mono text-xs text-on-surface">{row.code}</td>
                <td className="py-2.5 text-on-surface-variant">{row.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* --- fees ------------------------------------------------------ */}

      <h2 className="text-2xl font-bold text-on-surface mt-12 mb-4">Fees</h2>
      <p className="text-on-surface-variant mb-4 max-w-2xl">
        The standard tariff is <strong>1% of the payout</strong>, the same for every destination —
        every mobile money network, Selcom Pesa and every bank. Accounts with a negotiated rate pay
        that instead.
      </p>
      <p className="text-on-surface-variant mb-6 max-w-2xl">
        The fee is added to the amount, not taken out of it. A TZS 1,000 payout debits TZS 1,010
        from your wallet and the beneficiary receives TZS 1,000. It is calculated when the payout is
        created and stored on it.
      </p>

      {/* --- rejections ------------------------------------------------ */}

      <h2 className="text-2xl font-bold text-on-surface mt-12 mb-4">When a request is refused</h2>
      <p className="text-on-surface-variant mb-4 max-w-2xl">
        These are refused before anything is reserved, so no payout is created and no money moves:
      </p>
      <ul className="list-disc pl-5 space-y-2 text-on-surface-variant mb-6 max-w-2xl">
        <li>
          <Code>422</Code> — the Disbursement API is not enabled for the account, the amount is
          above a per-payout limit, the body is invalid, or a required header is missing. A field
          we do not recognise is a <Code>422</Code> too, including a missing{" "}
          <Code>Idempotency-Key</Code>.
        </li>
        <li>
          <Code>404</Code> — the beneficiary is not yours, not in this environment, disabled, or
          does not exist.
        </li>
        <li>
          <Code>409</Code> — payouts are paused on the account, or the rolling 24-hour limit would
          be exceeded.
        </li>
        <li>
          <Code>409 insufficient_balance</Code> — the wallet cannot cover the amount plus the fee.
          Fund the wallet and try again.
        </li>
      </ul>

      {/* --- sandbox --------------------------------------------------- */}

      <h2 className="text-2xl font-bold text-on-surface mt-12 mb-4">Sandbox</h2>
      <p className="text-on-surface-variant mb-6 max-w-2xl">
        Sandbox payouts reach Selcom&apos;s sandbox, not production: no real money moves and no real
        recipient is paid. Sandbox and live are separate grants, separate keys, separate
        beneficiaries and separate wallets, and nothing crosses between them.
      </p>

      <DocsPager currentHref="/developers/payouts" />
    </div>
  );
}
