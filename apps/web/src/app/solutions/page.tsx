import Link from "next/link";

import { Icon } from "@/components/portal/icon";
import { CTASection } from "@/components/site/cta-section";
import { FeatureGrid } from "@/components/site/feature-grid";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { SectionHeading } from "@/components/site/section-heading";
import { SolutionCard } from "@/components/site/solution-card";

export const metadata = {
  title: "Solutions | InfinityPay",
  description: "Every way InfinityPay helps Tanzanian merchants collect and manage payments — from mobile money collections to secure API integration.",
};

const SOLUTIONS = [
  {
    icon: "payments",
    title: "Mobile Money Collections",
    description: "Accept payments from any mobile money wallet in Tanzania, initiated with a single API call or from the merchant portal.",
  },
  {
    icon: "phone_iphone",
    title: "Push USSD",
    description: "Send a USSD collection prompt directly to a customer's phone — no app or internet connection required to pay.",
  },
  {
    icon: "touch_app",
    title: "STK Push",
    description: "Trigger a SIM Toolkit payment prompt so customers can approve a charge in a few taps from their phone's menu.",
  },
  {
    icon: "bolt",
    title: "Push to Selcom Pesa",
    description: "Send a payment request straight to a customer's Selcom Pesa wallet for fast, reliable confirmation.",
  },
  {
    icon: "link",
    title: "Payment Links",
    description: "Create a shareable payment link with amount, description, and expiry — send it via SMS, WhatsApp, or email.",
  },
  {
    icon: "receipt_long",
    title: "Invoice Creation",
    description: "Build itemized invoices with due dates and a built-in Pay Now link so customers can settle instantly.",
  },
  {
    icon: "account_balance_wallet",
    title: "Merchant Wallet Visibility",
    description: "Get a centralized, real-time view of your collected balance across every payment channel you use.",
  },
  {
    icon: "monitoring",
    title: "Transaction Monitoring",
    description: "Real-time visibility into every incoming transaction, with instant alerts on your dashboard.",
  },
  {
    icon: "api",
    title: "Secure API Integration",
    description: "RESTful APIs and sandbox testing built for modern development teams.",
  },
  {
    icon: "webhook",
    title: "Webhooks for Developers",
    description: "Get signed, real-time event notifications the moment a payment link is paid or an invoice settles.",
  },
];

export default function SolutionsPage() {
  return (
    <div className="bg-surface text-on-surface antialiased">
      <Header />
      <main>
        <section className="py-16 md:py-20 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading
              eyebrow="Solutions"
              title="Everything Your Business Needs to Get Paid"
              description="From mobile money collections to secure API integration, InfinityPay gives Tanzanian merchants one platform for every payment flow."
            />
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[1280px] mx-auto">
            <FeatureGrid columns={3}>
              {SOLUTIONS.map((solution) => (
                <SolutionCard key={solution.title} icon={solution.icon} title={solution.title} description={solution.description} />
              ))}
            </FeatureGrid>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto grid sm:grid-cols-3 gap-6 text-center">
            <Link href="/payment-links" className="bg-surface border border-outline-variant/40 rounded-xl p-6 hover:border-primary-container transition-colors">
              <Icon name="link" className="text-primary-container text-[28px] mb-2 block mx-auto" />
              <p className="text-sm font-bold text-on-surface mb-1">Payment Links</p>
              <p className="text-xs text-on-surface-variant">See how shareable links work</p>
            </Link>
            <Link href="/invoices" className="bg-surface border border-outline-variant/40 rounded-xl p-6 hover:border-primary-container transition-colors">
              <Icon name="receipt_long" className="text-primary-container text-[28px] mb-2 block mx-auto" />
              <p className="text-sm font-bold text-on-surface mb-1">Invoices</p>
              <p className="text-xs text-on-surface-variant">See how Pay Now invoices work</p>
            </Link>
            <Link href="/api-docs" className="bg-surface border border-outline-variant/40 rounded-xl p-6 hover:border-primary-container transition-colors">
              <Icon name="api" className="text-primary-container text-[28px] mb-2 block mx-auto" />
              <p className="text-sm font-bold text-on-surface mb-1">API Docs</p>
              <p className="text-xs text-on-surface-variant">Integrate every solution via API</p>
            </Link>
          </div>
        </section>

        <CTASection
          title="Ready to put these solutions to work?"
          description="Tell us what your business needs and our team will help you get set up fast."
          primaryLabel="Get Started"
          primaryHref="/create-account"
          secondaryLabel="Talk to Sales"
          secondaryHref="/contact"
        />
      </main>
      <Footer />
    </div>
  );
}
