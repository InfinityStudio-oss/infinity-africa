import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";

export const metadata = {
  title: "Account creation requirements",
};

const SIGNUP_FIELDS: Array<{ label: string; description: string; required: boolean }> = [
  { label: "Business name", description: "The trading name customers will see on receipts and payment pages.", required: true },
  { label: "Your name", description: "The person opening the account and responsible for it.", required: true },
  { label: "Business type", description: "What the business does — e.g. Retail, Logistics, Restaurant.", required: true },
  { label: "NIDA number", description: "20-digit Tanzanian National ID for the account owner.", required: true },
  { label: "Email", description: "Used to sign in, and where the verification link and account notices are sent.", required: true },
  { label: "Business phone", description: "Reachable number for account and compliance matters.", required: true },
  { label: "TIN", description: "Taxpayer Identification Number. Optional at signup; may be requested during review.", required: false },
  { label: "Website or app link", description: "Where the business operates online, if it does.", required: false },
  { label: "Password", description: "At least 8 characters, with uppercase, lowercase, a number and a symbol.", required: true },
]


export default function OnboardingRequirementsPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Getting Started</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Account creation requirements</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-6 max-w-2xl">
        Everything needed to open an InfinityPay account, and what happens after you submit it.
      </p>

      <section className="mb-10 max-w-2xl">
        <h2 className="text-xl font-semibold text-on-surface mb-3">How it works</h2>
        <ol className="text-sm text-on-surface-variant leading-relaxed space-y-2 list-decimal pl-5">
          <li>
            Fill in the form at <a href="/create-account" className="text-primary font-semibold hover:underline">Get Started</a> —
            business details and your password, on one page.
          </li>
          <li>Verify your email from the link sent to the address you entered.</li>
          <li>InfinityPay reviews the business. You can sign in while this is pending.</li>
          <li>Once approved, live API keys and withdrawals unlock.</li>
        </ol>
      </section>

      <div className="mb-10 max-w-2xl">
        <Callout title="No documents are uploaded at signup">
          The form collects business details only. If the compliance team needs identity, tax or licence documents,
          it asks for them directly during review — they appear under Document Requests in your dashboard. There is
          nothing to prepare in advance.
        </Callout>
      </div>

      <div className="mb-10 max-w-2xl">
        <Callout title="Approval gates live API access and withdrawals">
          An account must be approved before a withdrawal is accepted; an unapproved account is refused with a{" "}
          <code className="font-mono text-xs">withdrawal_restricted</code> error. Live API keys are issued only once
          review is complete. Sandbox keys are available sooner, so you can build while you wait.
        </Callout>
      </div>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">What the form asks for</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border border-outline-variant/40 rounded-xl overflow-hidden">
            <thead className="bg-surface-container-low">
              <tr>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Field</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Details</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant" />
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {SIGNUP_FIELDS.map((field) => (
                <tr key={field.label}>
                  <td className="px-4 py-2.5 font-medium text-on-surface align-top">{field.label}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant align-top">{field.description}</td>
                  <td className="px-4 py-2.5 align-top whitespace-nowrap">
                    {!field.required && (
                      <span className="bg-surface-container-highest text-on-surface-variant px-2.5 py-1 rounded-full text-xs font-semibold">
                        Optional
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          You also accept the Terms of Service and Privacy Policy, and confirm the details are accurate. That is the
          whole form — there is no second step and no upload.
        </p>
      </section>

      <section>
        <h2 className="text-xl font-semibold text-on-surface mb-3">Review outcomes</h2>
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
                ["PENDING_VERIFICATION", "Submitted, awaiting InfinityPay review."],
                ["VERIFIED", "Approved — account is active and verified, live API access and withdrawals unlocked."],
                ["REJECTED", "Declined — see the review note for why, and resubmit with corrections."],
                ["INFO_REQUESTED", "InfinityPay needs more information or documents before deciding — resubmit once addressed."],
              ].map(([status, meaning]) => (
                <tr key={status}>
                  <td className="px-4 py-2.5 font-mono text-xs text-on-surface whitespace-nowrap">{status}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant">{meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <DocsPager currentHref="/developers/onboarding-requirements" />
    </div>
  );
}
