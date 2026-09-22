import Link from "next/link";

import { Icon } from "@/components/portal/icon";
import { CTASection } from "@/components/site/cta-section";
import { FeatureGrid } from "@/components/site/feature-grid";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { SectionHeading } from "@/components/site/section-heading";

export const metadata = {
  title: "API Docs | InfinityPay",
  description: "Developer documentation for the InfinityPay REST API — authentication, Collections, Payment Links, Invoices, webhooks, transaction status, error codes, and code examples.",
};

const DOC_LINKS = [
  { label: "REST API Overview", href: "/developers", icon: "api", description: "Base URL, request/response envelope, and general conventions." },
  { label: "API Key Authentication", href: "/developers/authentication", icon: "vpn_key", description: "Sandbox vs. live keys and how to sign requests." },
  { label: "Collections API", href: "/developers/collections", icon: "payments", description: "Infinity Payment Page, Mobile Money Push, Selcom Pesa, and Scan QR / TanQR." },
  { label: "Payment Links API", href: "/developers/payment-links", icon: "link", description: "Create, fetch, and expire payment links." },
  { label: "Invoices API", href: "/developers/invoices", icon: "receipt_long", description: "Create invoices and track payment status." },
  { label: "Webhooks", href: "/developers/webhooks", icon: "webhook", description: "Event types, status lifecycle, payloads, and signature verification." },
  { label: "Error Codes", href: "/developers/errors", icon: "error", description: "Full reference of API error codes." },
  { label: "Go-Live Checklist", href: "/developers/go-live-checklist", icon: "checklist", description: "What to confirm before sending real customer traffic." },
  { label: "Sandbox Examples", href: "/developers/sandbox", icon: "science", description: "Test credentials and canned sandbox responses." },
  { label: "cURL Examples", href: "/developers/curl-examples", icon: "terminal", description: "Copy-paste cURL requests for every endpoint." },
  { label: "JavaScript Example", href: "/developers/javascript-example", icon: "code", description: "Node.js integration walkthrough." },
  { label: "Python Example", href: "/developers/python-example", icon: "code", description: "Python integration walkthrough." },
];

const INTEGRATORS = [
  { icon: "language", title: "Websites", description: "Drop a payment link or invoice checkout into any website — no SDK required." },
  { icon: "smartphone", title: "Mobile Apps", description: "Call the REST API directly from iOS or Android apps to collect payments and manage invoices." },
  { icon: "storefront", title: "Ecommerce Platforms", description: "Wire InfinityPay into your storefront's checkout flow for mobile money and cards." },
  { icon: "web", title: "Web Apps", description: "Integrate collections, payment links, and invoices into any internal or customer-facing web app." },
];

export default function ApiDocsPage() {
  return (
    <div className="bg-surface text-on-surface antialiased">
      <Header />
      <main>
        <section className="py-16 md:py-20 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto grid md:grid-cols-2 gap-14 items-start">
            <div className="min-w-0">
              <span className="text-xs font-semibold text-primary-container uppercase tracking-wide">API Docs</span>
              <h1 className="text-2xl md:text-4xl font-bold mt-2 mb-4 text-on-surface tracking-tight">
                Build on InfinityPay&apos;s payment API
              </h1>
              <p className="text-base text-on-surface-variant max-w-lg mb-6">
                RESTful APIs, signed webhooks, and clear documentation built for modern development teams — go from
                sandbox to production fast, whether you&apos;re integrating a website, mobile app, or ecommerce
                platform.
              </p>
              <Link
                href="/developers"
                className="inline-flex items-center gap-2 bg-primary-container text-on-primary text-sm font-medium px-6 py-3 rounded-lg hover:opacity-90 transition-opacity"
              >
                Open Full Documentation
                <Icon name="arrow_forward" className="text-[18px]" />
              </Link>
            </div>
            <div className="bg-on-surface rounded-xl p-6 shadow-ambient-lg font-mono text-[11px] leading-relaxed text-primary-fixed overflow-x-auto">
              <span className="text-white/40">POST</span> /v1/payment-links
              <br />
              <span className="text-white/40">Authorization:</span> Bearer inf_live_xxxxxxxxxxxxx
              <br />
              {"{"}
              <br />
              &nbsp;&nbsp;&quot;amount&quot;: &quot;25000.00&quot;,
              <br />
              &nbsp;&nbsp;&quot;currency&quot;: &quot;TZS&quot;,
              <br />
              &nbsp;&nbsp;&quot;merchant_id&quot;: &quot;...&quot;,
              <br />
              &nbsp;&nbsp;&quot;customer_phone&quot;: &quot;+255 7XX XXX XXX&quot;
              <br />
              {"}"}
              <br />
              <span className="text-white/40">→ 201 Created · link generated</span>
            </div>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading eyebrow="Reference" title="Everything You Need to Integrate" description="Each guide below links to the full reference documentation." />
            <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {DOC_LINKS.map((doc) => (
                <Link key={doc.href} href={doc.href}>
                  <div className="h-full bg-surface-container-lowest border border-outline-variant/40 rounded-xl p-6 shadow-ambient hover:shadow-ambient-lg hover:-translate-y-0.5 transition-all duration-200">
                    <div className="w-10 h-10 rounded-lg bg-primary-container/10 flex items-center justify-center mb-4">
                      <Icon name={doc.icon} className="text-primary-container text-[22px]" />
                    </div>
                    <h3 className="text-sm font-bold text-on-surface mb-1.5">{doc.label}</h3>
                    <p className="text-sm text-on-surface-variant leading-relaxed">{doc.description}</p>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading eyebrow="Who Integrates" title="Built for However You Build" description="InfinityPay's API works anywhere your business already lives." />
            <div className="mt-10">
              <FeatureGrid columns={4}>
                {INTEGRATORS.map((item) => (
                  <div key={item.title} className="bg-surface border border-outline-variant/40 rounded-xl p-6 text-center">
                    <Icon name={item.icon} className="text-primary-container text-[28px] mb-3 block mx-auto" />
                    <h3 className="text-sm font-bold text-on-surface mb-1.5">{item.title}</h3>
                    <p className="text-sm text-on-surface-variant leading-relaxed">{item.description}</p>
                  </div>
                ))}
              </FeatureGrid>
            </div>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading eyebrow="Merchant Account Operations" title="Beyond Collection" description="A small set of account-level operations live outside the public API docs, gated behind merchant verification." />
            <div className="mt-10 max-w-2xl mx-auto bg-surface-container-lowest border border-outline-variant/40 rounded-xl p-6 flex items-start gap-4">
              <div className="w-11 h-11 rounded-lg bg-primary-container/10 flex items-center justify-center shrink-0">
                <Icon name="lock" className="text-primary-container text-[22px]" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-on-surface mb-1.5">Withdrawal APIs</h3>
                <p className="text-sm text-on-surface-variant leading-relaxed">
                  Withdrawal APIs are available to approved merchants after onboarding and verification. Reference
                  documentation lives in the authenticated merchant/developer portal.
                </p>
              </div>
            </div>
          </div>
        </section>

        <CTASection
          title="Start integrating today"
          description="Create a merchant account, then generate a sandbox key from the Merchant Portal to make your first API call in minutes."
          primaryLabel="Create Merchant Account to Generate API Keys"
          primaryHref="/create-account"
          secondaryLabel="Already have an account? Log in"
          secondaryHref="/dashboard/login"
        />
      </main>
      <Footer />
    </div>
  );
}
