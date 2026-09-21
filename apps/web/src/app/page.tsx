import Link from "next/link";

import { AuthFragmentRedirect } from "@/components/auth/auth-fragment-redirect";
import { CTASection } from "@/components/site/cta-section";
import { ContactCard } from "@/components/site/contact-card";
import { FeatureGrid } from "@/components/site/feature-grid";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { SectionHeading } from "@/components/site/section-heading";
import { SolutionCard } from "@/components/site/solution-card";
import { Icon } from "@/components/portal/icon";

export const metadata = {
  title: "InfinityPay — Collect Payments, Create Links, and Get Paid Faster in Tanzania",
  description:
    "InfinityPay helps merchants accept mobile money payments, create secure payment links, generate invoices, and integrate payment collection into websites, mobile apps, ecommerce platforms, and web apps.",
};

const NETWORKS = [
  { label: "M-Pesa" },
  { label: "Tigo Pesa" },
  { label: "Airtel Money" },
  { label: "HaloPesa" },
  { label: "Selcom Pesa", featured: true },
  { label: "CRDB Bank" },
  { label: "NMB Bank" },
];

const HIGHLIGHTS = [
  {
    icon: "payments",
    title: "Mobile Money Collections",
    description: "Push USSD, STK Push, or Selcom Pesa Push straight to a customer's phone — one API for every channel.",
    chips: ["Push USSD", "STK Push", "Selcom Pesa Push"],
  },
  {
    icon: "link",
    title: "Payment Links",
    description: "Generate a secure payment link in seconds and share it via SMS, WhatsApp, or email — no website required.",
  },
  {
    icon: "receipt_long",
    title: "Invoices",
    description: "Create professional itemized invoices with built-in Pay Now links so customers can settle instantly.",
  },
  {
    icon: "api",
    title: "API Integration",
    description: "A secure, versioned REST API with signed webhooks — integrate collection into any website, app, or platform.",
  },
];

const HOW_IT_WORKS = [
  { step: 1, title: "Create Your Account", description: "Sign up and get verified as a merchant in minutes." },
  { step: 2, title: "Collect Payments", description: "Accept mobile money, share payment links, or send invoices with Pay Now." },
  { step: 3, title: "Track in Real Time", description: "Monitor collections, balances, and payment status from one dashboard." },
  { step: 4, title: "Get Paid Faster", description: "Funds settle to your available balance — manage withdrawals anytime from your merchant portal." },
];

const SECURITY_POINTS = [
  { icon: "lock", label: "Bank-grade encryption for every transaction" },
  { icon: "monitoring", label: "Real-time fraud monitoring and alerts" },
  { icon: "account_balance", label: "Segregated merchant funds" },
  { icon: "verified", label: "Registered Payment Service Provider in Tanzania" },
  { icon: "groups", label: "Role-based access control for your team" },
  { icon: "api", label: "Secure, versioned REST API with signed webhooks" },
];

export default function Home() {
  return (
    <div className="bg-surface text-on-surface antialiased selection:bg-primary-container selection:text-on-primary-container">
      <AuthFragmentRedirect />
      <Header />

      <main>
        {/* Hero */}
        <section className="relative pt-10 md:pt-14 pb-14 px-4 md:px-10 max-w-[1280px] mx-auto overflow-hidden">
          <div className="relative z-10 grid md:grid-cols-2 gap-14 items-center">
            <div className="space-y-8">
              <h1 className="text-2xl sm:text-3xl md:text-5xl font-bold text-on-surface leading-tight tracking-tight">
                Collect Payments. <span className="text-primary-container">Create Payment Links.</span> Get Paid
                Faster.
              </h1>
              <p className="text-lg text-on-surface-variant max-w-xl leading-relaxed">
                InfinityPay helps merchants accept mobile money payments, create secure payment links, generate
                invoices, and integrate payment collection into websites, mobile apps, ecommerce platforms, and web
                apps.
              </p>
              <p className="text-sm text-on-surface-variant/80 max-w-xl">
                Merchants can manage collected funds from their merchant portal after verification.
              </p>
              <div className="flex flex-col sm:flex-row gap-4">
                <Link
                  href="/create-account"
                  className="bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-all shadow-ambient-lg w-full sm:w-auto text-center inline-flex items-center justify-center gap-2"
                >
                  Start Integration
                  <Icon name="arrow_forward" className="text-[18px]" />
                </Link>
                <Link
                  href="/api-docs"
                  className="bg-surface border border-outline-variant text-on-surface text-sm font-medium px-8 py-3.5 rounded-lg hover:border-primary-container hover:text-primary-container transition-all w-full sm:w-auto text-center"
                >
                  View API Docs
                </Link>
              </div>
            </div>

            {/* Hero visual: self-contained product mockup */}
            <div className="relative flex items-center justify-center py-4">
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-primary-container/20 rounded-full blur-3xl" />
              <div className="absolute top-1/2 left-1/2 -translate-x-1/3 -translate-y-1/3 w-64 h-64 bg-primary/10 rounded-full blur-3xl" />

              <div className="relative z-10 w-[260px] sm:w-[290px] rounded-[2.5rem] bg-on-surface p-2.5 shadow-ambient-lg">
                <div className="rounded-[2rem] bg-gradient-to-b from-surface-container-lowest to-surface-container-low overflow-hidden p-4 space-y-4">
                  <div className="flex justify-between items-center text-[10px] text-on-surface-variant font-semibold px-1">
                    <span>9:41</span>
                    <div className="flex items-center gap-1">
                      <Icon name="signal_cellular_alt" className="text-[14px]" />
                      <Icon name="battery_full" className="text-[14px]" />
                    </div>
                  </div>
                  <div className="flex justify-between items-center px-1">
                    <span className="text-sm font-bold text-on-surface">InfinityPay</span>
                    <div className="w-7 h-7 rounded-full bg-primary-container/20 flex items-center justify-center">
                      <Icon name="person" className="text-[16px] text-primary-container" />
                    </div>
                  </div>
                  <div className="bg-primary-container rounded-2xl p-4 text-on-primary shadow-ambient">
                    <p className="text-[11px] opacity-80">Total Balance</p>
                    <p className="text-2xl font-bold tracking-tight">TZS 4,850,000</p>
                    <div className="flex items-center gap-1 text-[11px] mt-1 opacity-90">
                      <Icon name="trending_up" className="text-[14px]" />
                      +12.4% this month
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { icon: "payments", label: "Collect" },
                      { icon: "link", label: "Link" },
                      { icon: "receipt_long", label: "Invoice" },
                    ].map((action) => (
                      <div key={action.label} className="bg-surface-container-lowest rounded-xl shadow-sm p-2 flex flex-col items-center gap-1">
                        <Icon name={action.icon} className="text-[18px] text-primary-container" />
                        <span className="text-[9px] font-semibold text-on-surface-variant">{action.label}</span>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2.5 pt-1">
                    {[
                      { icon: "link", title: "Payment Link · Grace M.", subtitle: "via M-Pesa", amount: "+25,000", muted: false },
                      { icon: "receipt_long", title: "Invoice #1042", subtitle: "Paid by customer", amount: "+120,000", muted: false },
                      { icon: "payments", title: "Collection · Neema Salon", subtitle: "via Airtel Money", amount: "+18,000", muted: false },
                    ].map((row) => (
                      <div key={row.title} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className={`w-7 h-7 rounded-full flex items-center justify-center ${row.muted ? "bg-on-surface-variant/10" : "bg-primary-container/10"}`}>
                            <Icon name={row.icon} className={`text-[14px] ${row.muted ? "text-on-surface-variant" : "text-primary-container"}`} />
                          </div>
                          <div>
                            <p className="text-[11px] font-semibold text-on-surface leading-tight">{row.title}</p>
                            <p className="text-[9px] text-on-surface-variant leading-tight">{row.subtitle}</p>
                          </div>
                        </div>
                        <span className={`text-[11px] font-bold ${row.muted ? "text-on-surface-variant" : "text-primary-container"}`}>{row.amount}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Trust strip */}
        <section className="border-y border-outline-variant/50 bg-surface-container-lowest py-8">
          <div className="max-w-[1280px] mx-auto px-4 md:px-10">
            <p className="text-center text-xs font-semibold text-on-surface-variant mb-5">
              Integrated with Tanzania&apos;s leading mobile money and banking networks
            </p>
            <div className="flex flex-wrap justify-center gap-3">
              {NETWORKS.map((network) => (
                <span
                  key={network.label}
                  className={
                    network.featured
                      ? "px-4 py-2 rounded-full border border-primary-container/30 bg-primary-container/5 text-primary text-xs font-semibold"
                      : "px-4 py-2 rounded-full border border-outline-variant text-on-surface-variant text-xs font-semibold"
                  }
                >
                  {network.label}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Highlights */}
        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading
              eyebrow="Platform"
              title="Powerful Payment Infrastructure"
              description="Everything you need to collect, link, invoice, and move money seamlessly across Tanzania."
            />
            <div className="mt-10">
              <FeatureGrid columns={3}>
                {HIGHLIGHTS.map((item) => (
                  <SolutionCard key={item.title} icon={item.icon} title={item.title} description={item.description} chips={item.chips} />
                ))}
              </FeatureGrid>
            </div>
            <div className="text-center mt-10">
              <Link
                href="/solutions"
                className="inline-flex items-center gap-2 text-primary-container text-sm font-semibold hover:underline"
              >
                View All Solutions
                <Icon name="arrow_forward" className="text-[18px]" />
              </Link>
            </div>
          </div>
        </section>

        {/* How It Works */}
        <section className="py-14 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading eyebrow="Process" title="How It Works" description="From setup to settlement in four simple steps." />
            <div className="relative grid grid-cols-1 md:grid-cols-4 gap-8 md:gap-5 mt-10">
              <div className="hidden md:block absolute top-5 left-0 right-0 h-px bg-outline-variant" style={{ margin: "0 12.5%" }} />
              {HOW_IT_WORKS.map((item) => (
                <div key={item.step} className="relative text-center">
                  <div className="w-10 h-10 mx-auto rounded-full bg-primary-container text-on-primary flex items-center justify-center font-bold text-sm shadow-ambient relative z-10">
                    {item.step}
                  </div>
                  <h3 className="text-sm font-bold text-on-surface mt-3 mb-1">{item.title}</h3>
                  <p className="text-sm text-on-surface-variant leading-relaxed px-2">{item.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Security */}
        <section className="py-24 px-4 md:px-10 bg-surface">
          <div className="max-w-[1280px] mx-auto grid md:grid-cols-2 gap-14 items-center">
            <div>
              <span className="text-xs font-semibold text-primary-container uppercase tracking-wide">Security</span>
              <h2 className="text-2xl md:text-4xl font-bold mt-2 mb-4 text-on-surface tracking-tight">Security and Trust</h2>
              <p className="text-base text-on-surface-variant mb-8 max-w-lg">
                InfinityPay is built to move your customers&apos; money with the same rigor as a bank — so you can focus on
                growing your business.
              </p>
              <div className="grid sm:grid-cols-2 gap-x-6 gap-y-5">
                {SECURITY_POINTS.map((point) => (
                  <div key={point.label} className="flex items-start gap-3">
                    <Icon name={point.icon} className="text-primary-container text-[22px]" />
                    <span className="text-sm text-on-surface-variant leading-relaxed">{point.label}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="relative bg-gradient-to-br from-primary-container/5 to-surface-container-lowest border border-primary-container/15 rounded-2xl p-10 shadow-ambient flex flex-col items-center text-center">
              <div className="w-20 h-20 rounded-full bg-primary-container/10 flex items-center justify-center mb-4">
                <Icon name="shield" className="text-primary text-[44px]" />
              </div>
              <h3 className="text-2xl font-semibold text-on-surface mb-2">Protected by design</h3>
              <p className="text-sm text-on-surface-variant mb-8 max-w-xs">Every layer of InfinityPay is monitored, encrypted, and audited.</p>
              <div className="grid grid-cols-3 gap-4 w-full">
                {[
                  { value: "99.9%", label: "Uptime" },
                  { value: "256-bit", label: "Encryption" },
                  { value: "24/7", label: "Monitoring" },
                ].map((stat) => (
                  <div key={stat.label}>
                    <p className="text-2xl font-semibold text-primary">{stat.value}</p>
                    <p className="text-xs font-semibold text-on-surface-variant mt-1">{stat.label}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Contact summary */}
        <section className="py-16 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading eyebrow="Contact" title="Let's Talk" description="Have questions about integration, pricing, or getting your business set up? Our team in Dar es Salaam is ready to help." />
            <div className="grid sm:grid-cols-3 gap-6 mt-10 max-w-3xl mx-auto">
              <ContactCard icon="mail" label="Business Email" value="info@infinitypay.me" href="mailto:info@infinitypay.me" />
              <ContactCard icon="call" label="Customer Support" value="+255 747 730 270" href="https://wa.me/255747730270" />
              <ContactCard icon="location_on" label="Headquarters" value="Mbezi Luis - Ubungo - Dar es Salaam" />
            </div>
            <div className="text-center mt-10">
              <Link href="/contact" className="inline-flex items-center gap-2 text-primary-container text-sm font-semibold hover:underline">
                Go to Contact Page
                <Icon name="arrow_forward" className="text-[18px]" />
              </Link>
            </div>
          </div>
        </section>

        <CTASection
          title="Ready to start collecting payments?"
          description="Tell us about your business and our team will help you get integrated in days, not weeks."
          primaryLabel="Get Started"
          primaryHref="/create-account"
          secondaryLabel="View API Docs"
          secondaryHref="/api-docs"
        />
      </main>

      <Footer />
    </div>
  );
}
