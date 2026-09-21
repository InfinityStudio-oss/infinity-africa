import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { Icon } from "@/components/portal/icon";

export const metadata = {
  title: "Privacy Policy | InfinityPay",
  description: "Privacy Policy for the InfinityPay payment platform.",
};

const SECTIONS: { title: string; body: string; items?: string[] }[] = [
  {
    title: "1. Introduction",
    body: "InfinityPay respects your privacy and is committed to protecting the information of our merchants, their customers, and the transactions processed through our platform. This Privacy Policy explains what information we collect, how we use it, and the choices you have.",
  },
  {
    title: "2. Information We Collect",
    body: "Depending on how you use InfinityPay, we may collect:",
    items: [
      "Account information (name, email address, password)",
      "Business details (business name, category, nature of business)",
      "Contact details (phone number, physical address)",
      "Customer payment details submitted through collections, payment links, and invoices",
      "Transaction data (amounts, references, statuses, timestamps)",
      "API usage data (requests, API keys, webhook activity)",
      "Device and browser data (IP address, device type, log data)",
    ],
  },
  {
    title: "3. Business Verification Documents",
    body: "As part of merchant onboarding and verification, we collect:",
    items: [
      "National Identification Authority (NIDA) details",
      "TIN certificate",
      "Business licence",
      "Physical address",
      "Nature of business",
    ],
  },
  {
    title: "4. How We Use Information",
    body: "We use the information we collect for:",
    items: [
      "Account creation and management",
      "Merchant verification",
      "Payment processing",
      "Payment link and invoice management",
      "Transaction monitoring",
      "Fraud prevention",
      "Customer support",
      "Compliance with applicable laws and regulations",
      "API and account security",
    ],
  },
  {
    title: "5. Payment and Transaction Data",
    body: "InfinityPay stores transaction references, statuses, amounts, payment methods, timestamps, and related metadata. This data is used for reconciliation, reporting, and to give merchants an accurate record of their collections, payment links, and invoices.",
  },
  {
    title: "6. Data Sharing",
    body: "InfinityPay does not sell your personal information. Data may be shared with merchants (where necessary to notify them of a customer dispute or fraud review and request a response), payment providers, banks and mobile money operators, compliance and verification partners, service providers who support our platform, and lawful authorities where legally required — solely as necessary to provide and secure our services, review fraud or disputes, process refunds, or meet compliance obligations.",
  },
  {
    title: "7. Data Security",
    body: "InfinityPay applies technical and organizational safeguards to protect information, including encryption of data in transit, access controls, audit logs, secure authentication, and restricted access to sensitive data on a need-to-know basis.",
  },
  {
    title: "8. Data Retention",
    body: "InfinityPay retains records for as long as necessary for business operations, legal and regulatory compliance, audit purposes, and fraud prevention, even after an account is closed, where required by law or legitimate business need. Fraud, dispute, transaction, and compliance records — including documents submitted for review — may be retained for extended periods for legal, audit, security, and business purposes.",
  },
  {
    title: "9. User Rights",
    body: "Merchants may request access to, correction of, or an update to their information, or contact support for help with their account, subject to InfinityPay's legal and regulatory obligations to retain certain records.",
  },
  {
    title: "10. Cookies and Analytics",
    body: "InfinityPay uses cookies and similar technologies for essential purposes such as security, keeping you signed in, and session management, as well as basic analytics to help us understand and improve how our services are used.",
  },
  {
    title: "11. API and Developer Data",
    body: "For merchants and developers integrating with InfinityPay, we store API keys, webhook delivery logs, and integration activity. This information is used for security monitoring, troubleshooting, and helping developers debug their integrations.",
  },
  {
    title: "12. Children's Privacy",
    body: "InfinityPay's services are intended for businesses and merchants, not for children. We do not knowingly collect personal information from children.",
  },
  {
    title: "13. Changes to This Privacy Policy",
    body: "InfinityPay may update this Privacy Policy from time to time. Continued use of the platform after changes take effect constitutes acceptance of the revised policy.",
  },
  {
    title: "14. Fraud and Risk Monitoring Data",
    body: "To detect and prevent suspicious activity, InfinityPay may process transaction metadata, customer phone numbers, timestamps, payment amounts, device and browser data, provider references, payment attempt history, and dispute history. This data is used to run automated fraud rules, raise alerts for review, and inform decisions about account and transaction restrictions.",
  },
  {
    title: "15. Supporting Documents",
    body: "InfinityPay may collect and store documents submitted for transaction review, disputes, onboarding, compliance, and merchant verification — including receipts, invoices, proof of delivery, customer communication, and product or service evidence. These documents are stored in access-controlled storage and are only ever retrieved via short-lived, signed links generated for authorized review.",
  },
  {
    title: "16. Dispute and Chargeback Data",
    body: "InfinityPay may collect customer reports, dispute descriptions, transaction references, evidence files, refund records, and communication related to a dispute — whether submitted by a customer through our public reporting form or by a merchant responding to one. This data is used to review the dispute, communicate with the parties involved, and process a refund where appropriate.",
  },
  {
    title: "17. Contact Information",
    body: "For questions about this Privacy Policy or your information, contact InfinityPay using the details below.",
  },
];

export default function PrivacyPage() {
  return (
    <div className="bg-surface text-on-surface antialiased flex min-h-full flex-col">
      <Header />
      <main className="flex-1">
        <section className="py-16 md:py-20 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[800px] mx-auto">
            <span className="text-xs font-semibold text-primary-container uppercase tracking-wide">Legal</span>
            <h1 className="text-2xl md:text-4xl font-bold mt-2 mb-3 text-on-surface tracking-tight">Privacy Policy</h1>
            <p className="text-sm text-on-surface-variant">
              Last updated {new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}
            </p>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[800px] mx-auto space-y-8">
            {SECTIONS.map((section) => (
              <div key={section.title}>
                <h2 className="text-lg font-semibold text-on-surface mb-2">{section.title}</h2>
                <p className="text-sm text-on-surface-variant leading-relaxed">{section.body}</p>
                {section.items && (
                  <ul className="mt-3 space-y-1.5 list-disc pl-5">
                    {section.items.map((item) => (
                      <li key={item} className="text-sm text-on-surface-variant leading-relaxed">
                        {item}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}

            <div className="rounded-xl border border-outline-variant/60 bg-surface-container-lowest p-6">
              <ul className="space-y-3">
                <li className="flex items-center gap-2.5 text-sm text-on-surface">
                  <Icon name="mail" className="text-[18px] text-primary-container" />
                  <a href="mailto:info@infinityafrica.net" className="hover:text-primary-container transition-colors">
                    info@infinityafrica.net
                  </a>
                </li>
                <li className="flex items-center gap-2.5 text-sm text-on-surface">
                  <Icon name="support_agent" className="text-[18px] text-primary-container" />
                  <a href="mailto:help@infinityafrica.net" className="hover:text-primary-container transition-colors">
                    help@infinityafrica.net
                  </a>
                </li>
                <li className="flex items-center gap-2.5 text-sm text-on-surface">
                  <Icon name="headset_mic" className="text-[18px] text-primary-container" />
                  <a href="mailto:info@infinityafrica.net" className="hover:text-primary-container transition-colors">
                    info@infinityafrica.net
                  </a>
                </li>
                <li className="flex items-center gap-2.5 text-sm text-on-surface">
                  <Icon name="call" className="text-[18px] text-primary-container" />
                  <a href="https://wa.me/255747730270" className="hover:text-primary-container transition-colors">
                    +255 747 730 270
                  </a>
                </li>
                <li className="flex items-center gap-2.5 text-sm text-on-surface">
                  <Icon name="language" className="text-[18px] text-primary-container" />
                  <a href="https://infinitypay.me" className="hover:text-primary-container transition-colors">
                    infinitypay.me
                  </a>
                </li>
                <li className="flex items-center gap-2.5 text-sm text-on-surface">
                  <Icon name="location_on" className="text-[18px] text-primary-container shrink-0" />
                  Mbezi - Ubungo - Dar es Salaam
                </li>
              </ul>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
