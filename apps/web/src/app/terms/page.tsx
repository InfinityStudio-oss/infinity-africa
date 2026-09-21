import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { Icon } from "@/components/portal/icon";

export const metadata = {
  title: "Terms of Service | InfinityPay",
  description: "Terms of Service for the InfinityPay payment platform.",
};

const SECTIONS: { title: string; body: string; items?: string[] }[] = [
  {
    title: "1. Introduction",
    body: "InfinityPay provides payment infrastructure tools for merchants in Tanzania, including payment collection, payment links, invoices, dynamic QR codes, API integrations, transaction monitoring, and merchant wallet visibility. By creating an account or using any InfinityPay service, you agree to these Terms of Service.",
  },
  {
    title: "2. Eligibility",
    body: "To use InfinityPay, merchants must provide accurate and complete business information and comply with all applicable Tanzanian laws, regulations, and verification requirements. InfinityPay may decline or restrict service to any business that does not meet these requirements.",
  },
  {
    title: "3. Account Registration",
    body: "To use InfinityPay's services, merchants must create an account, submit onboarding details about their business, provide any compliance information or documents InfinityPay requests during review, and accept these Terms of Service and the Privacy Policy. Live access to collections, payment links, API keys, and withdrawals is granted only after InfinityPay approves the merchant account.",
  },
  {
    title: "4. Merchant Verification",
    body: "Before activating full account functionality, InfinityPay may review a merchant's National Identification Authority (NIDA) details, Taxpayer Identification Number (TIN) certificate, business licence, business information, and other compliance details. InfinityPay may request additional information or documents at any time to complete or maintain verification.",
  },
  {
    title: "5. Merchant Responsibilities",
    body: "Merchants are responsible for providing accurate customer and payment information, conducting lawful business activity, maintaining secure access to their account and credentials, and ensuring correct and responsible use of InfinityPay's APIs and services.",
  },
  {
    title: "6. Payment Collections",
    body: "InfinityPay supports payment collection through methods such as Push USSD, STK Push, Selcom Pesa Push, and Dynamic QR, where available. Availability of specific collection methods may vary by mobile network operator, provider, and merchant configuration.",
  },
  {
    title: "7. Payment Links and Invoices",
    body: "Merchants may create payment links and invoices, including customer details, itemized amounts, expiry times, and built-in Pay Now links. InfinityPay provides tracking of payment status for links and invoices created through the merchant portal or API.",
  },
  {
    title: "8. Merchant Wallet and Withdrawals",
    body: "Collected funds are reflected in a merchant's wallet within the merchant portal. Withdrawals are not a public standalone service — only verified merchants may request withdrawals of available collected funds from the merchant portal, to supported destinations such as Selcom Pesa, mobile money wallets, or bank accounts, subject to available balance, applicable fees, and standard processing times.",
  },
  {
    title: "9. API Usage",
    body: "Merchants and developers may integrate websites, mobile apps, ecommerce platforms, and web apps using InfinityPay's REST APIs and signed webhooks. API access is granted through API keys, which must be kept confidential and used in accordance with InfinityPay's API documentation.",
  },
  {
    title: "10. Prohibited Activities",
    body: "Merchants may not use InfinityPay for:",
    items: [
      "Fraud or attempted fraud of any kind, including fraudulent transactions",
      "Sale of illegal goods or services",
      "Money laundering, terrorist financing, or other suspicious transaction patterns",
      "Unauthorized or unauthenticated transactions, including unauthorized charges",
      "Submission of fake, altered, or fraudulent documents",
      "Misrepresentation of products or services offered to customers",
      "Abuse, probing, or unauthorized use of InfinityPay's APIs or payment links",
      "Any activity that violates applicable Tanzanian law or payment network rules",
    ],
  },
  {
    title: "11. Fees",
    body: "Fees may vary by merchant, transaction type, payment method, transaction volume, or individual agreement. Applicable fees are disclosed to each merchant in the merchant portal and are not fixed or published as standard public pricing.",
  },
  {
    title: "12. Webhooks and Transaction Status",
    body: "Transaction status shown in the merchant portal or delivered via webhook may depend on payment provider callbacks, reconciliation processes, and settlement confirmation. InfinityPay is not responsible for delays caused by third-party providers or network operators.",
  },
  {
    title: "13. Account Suspension or Termination",
    body: "InfinityPay may suspend, restrict, or terminate a merchant account in cases of suspected fraud, compliance issues, misuse of the platform, or violation of these Terms, with or without prior notice where required to protect InfinityPay, its merchants, or customers.",
  },
  {
    title: "14. Limitation of Liability",
    body: "InfinityPay provides its platform on an \"as available\" basis and is not liable for indirect, incidental, or consequential damages arising from use of the platform, including delays or failures caused by third-party payment providers, mobile network operators, banking partners, or events outside InfinityPay's reasonable control.",
  },
  {
    title: "15. Changes to Terms",
    body: "InfinityPay may update these Terms of Service from time to time. Merchants should review this page periodically. Continued use of InfinityPay's services after changes take effect constitutes acceptance of the revised Terms.",
  },
  {
    title: "16. Fraud Monitoring and Transaction Review",
    body: "InfinityPay may monitor transactions for suspicious activity, using automated rules and manual review. InfinityPay may flag a transaction for review, place it under review, and request supporting documents from the merchant involved. While a review is ongoing, InfinityPay may restrict or delay access to funds related to the flagged transaction or, where the risk is high, temporarily restrict a merchant's withdrawals more broadly. Merchants must cooperate promptly and honestly with any review request.",
  },
  {
    title: "17. Supporting Documents",
    body: "As part of onboarding, compliance, or a transaction review, merchants may be required to submit receipts, invoices, proof of delivery, customer communication or agreements, product or service evidence, or other supporting documents. Failure to provide requested documents within a reasonable time may result in continued restriction of the affected funds or account.",
  },
  {
    title: "18. Customer Disputes and Chargebacks",
    body: "Customers may report transaction issues, product or service disputes, unauthorized payments, duplicate payments, or refund requests directly to InfinityPay. Where a report is received, InfinityPay may notify the merchant involved and request a response or supporting evidence. A merchant may be required to refund a customer where InfinityPay determines it is appropriate. InfinityPay may assist in reviewing a dispute but does not guarantee any particular outcome.",
  },
  {
    title: "19. Refunds",
    body: "Refunds may be processed after review, merchant approval, or confirmation from a payment provider, and are always made with reference to the original transaction. Refund timing may depend on the payment provider, mobile money operator, bank, or the internal review process involved, and is not guaranteed to complete within a fixed timeframe.",
  },
  {
    title: "20. Contact Information",
    body: "For questions about these Terms of Service, contact InfinityPay using the details below.",
  },
];

export default function TermsPage() {
  return (
    <div className="bg-surface text-on-surface antialiased flex min-h-full flex-col">
      <Header />
      <main className="flex-1">
        <section className="py-16 md:py-20 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[800px] mx-auto">
            <span className="text-xs font-semibold text-primary-container uppercase tracking-wide">Legal</span>
            <h1 className="text-2xl md:text-4xl font-bold mt-2 mb-3 text-on-surface tracking-tight">Terms of Service</h1>
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
                  <a href="mailto:info@infinitypay.me" className="hover:text-primary-container transition-colors">
                    info@infinitypay.me
                  </a>
                </li>
                <li className="flex items-center gap-2.5 text-sm text-on-surface">
                  <Icon name="support_agent" className="text-[18px] text-primary-container" />
                  <a href="mailto:help@infinitypay.me" className="hover:text-primary-container transition-colors">
                    help@infinitypay.me
                  </a>
                </li>
                <li className="flex items-center gap-2.5 text-sm text-on-surface">
                  <Icon name="headset_mic" className="text-[18px] text-primary-container" />
                  <a href="mailto:info@infinitypay.me" className="hover:text-primary-container transition-colors">
                    info@infinitypay.me
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
