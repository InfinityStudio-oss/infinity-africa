import { Callout } from "@/components/docs/callout";
import { DocsPager } from "@/components/docs/docs-pager";

export const metadata = {
  title: "Onboarding Requirements",
};

const REQUIRED_DOCUMENTS: Array<{ label: string; description: string; status: "Requested during review" | "Documentation only" }> = [
  {
    label: "NIDA (National ID) or authorized representative ID",
    description: "Proof of identity for the business owner or the person authorized to act on the business's behalf.",
    status: "Requested during review",
  },
  {
    label: "TIN certificate",
    description: "Tanzania Revenue Authority Taxpayer Identification Number certificate.",
    status: "Requested during review",
  },
  {
    label: "Business licence",
    description: "Current, valid business operating licence for the business's registered activity.",
    status: "Requested during review",
  },
  {
    label: "Business registration / incorporation certificate",
    description: "If your business is formally registered or incorporated (e.g. BRELA certificate). Provide if available.",
    status: "Documentation only",
  },
  {
    label: "Physical business address",
    description: "A verifiable street address — collected during onboarding, not a separate document upload.",
    status: "Documentation only",
  },
  {
    label: "Contact person details",
    description: "Full name, email, and phone number of the person InfinityPay should reach for account and compliance matters.",
    status: "Documentation only",
  },
  {
    label: "Bank account details",
    description: "Required only if you intend to withdraw to a bank account — bank name, account number, and account holder name.",
    status: "Documentation only",
  },
  {
    label: "Settlement / withdrawal destination details",
    description: "Whichever withdrawal channels you plan to use (Selcom Pesa, mobile money, and/or bank account) and their destination details.",
    status: "Documentation only",
  },
  {
    label: "Signed Terms of Service and Privacy Policy acceptance",
    description: "Accepted as part of the onboarding submission — see the Terms and Privacy pages.",
    status: "Documentation only",
  },
  {
    label: "Additional compliance documents",
    description: "InfinityPay's compliance team may request further documentation during review (see Document Requests in the dashboard).",
    status: "Documentation only",
  },
];

export default function OnboardingRequirementsPage() {
  return (
    <div>
      <p className="text-xs font-semibold text-primary uppercase tracking-wide mb-2">Getting Started</p>
      <h1 className="text-3xl md:text-4xl font-bold text-on-surface tracking-tight mb-4">Onboarding Requirements</h1>
      <p className="text-lg text-on-surface-variant leading-relaxed mb-6 max-w-2xl">
        What InfinityPay needs before your account is approved for live API access and withdrawals. Provide your
        business details through the onboarding flow at <code className="font-mono text-sm bg-surface-container-low px-1.5 py-0.5 rounded">/onboarding</code> after
        creating your account. Identity and compliance documents are not uploaded during onboarding — Infinity
        Africa&apos;s compliance team requests whatever it needs directly during review.
      </p>

      <div className="mb-10 max-w-2xl">
        <Callout title="Approval gates both API access and withdrawals">
          A account must be <code className="font-mono text-xs">active</code> and{" "}
          <code className="font-mono text-xs">verified</code> before any withdrawal request is accepted; an
          unapproved account is refused with a{" "}
          <code className="font-mono text-xs">withdrawal_restricted</code> error. Live API keys are only issued once
          onboarding review is complete.
        </Callout>
      </div>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-on-surface mb-3">Required documents and information</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border border-outline-variant/40 rounded-xl overflow-hidden">
            <thead className="bg-surface-container-low">
              <tr>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Requirement</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Details</th>
                <th className="px-4 py-2.5 font-semibold text-on-surface-variant">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {REQUIRED_DOCUMENTS.map((doc) => (
                <tr key={doc.label}>
                  <td className="px-4 py-2.5 font-medium text-on-surface align-top">{doc.label}</td>
                  <td className="px-4 py-2.5 text-on-surface-variant align-top">{doc.description}</td>
                  <td className="px-4 py-2.5 align-top whitespace-nowrap">
                    <span
                      className={
                        doc.status === "Requested during review"
                          ? "inline-flex items-center gap-1 bg-accent text-primary px-2.5 py-1 rounded-full text-xs font-semibold border border-primary/20"
                          : "bg-surface-container-highest text-on-surface-variant px-2.5 py-1 rounded-full text-xs font-semibold"
                      }
                    >
                      {doc.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-sm text-on-surface-variant leading-relaxed mt-4">
          The onboarding submission itself only collects your business details and Terms/Privacy acceptance. Nothing in
          the list above is uploaded through the onboarding form. Items marked <strong>&quot;Requested during
          review&quot;</strong> are asked for directly by InfinityPay&apos;s compliance team if needed (see Document
          Requests in the dashboard); everything marked &quot;Documentation only&quot; is either captured in the
          submission form or requested the same way.
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
