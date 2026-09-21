import { Icon } from "@/components/portal/icon";
import { CTASection } from "@/components/site/cta-section";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { SectionHeading } from "@/components/site/section-heading";

export const metadata = {
  title: "Payment Links | InfinityPay",
  description: "Create shareable payment links with amount, customer phone, description, and expiry — let customers pay however suits them best.",
};

const CREATE_FIELDS = [
  { icon: "payments", label: "Amount", description: "Set a fixed amount in TZS for the customer to pay." },
  { icon: "call", label: "Customer Phone", description: "Attach a phone number so the customer gets notified automatically." },
  { icon: "description", label: "Description", description: "Add context so the customer knows exactly what they're paying for." },
  { icon: "schedule", label: "Expiry Time", description: "Set how long the link stays valid before it automatically expires." },
];

const SHARE_CHANNELS = ["WhatsApp", "SMS", "Email", "Instagram", "Website Checkout"];

const PAYMENT_METHODS = [
  { icon: "smartphone", label: "Pay by Mobile Money Push", description: "Approve with your mobile money PIN" },
  { icon: "account_balance_wallet", label: "Pay with Selcom Pesa", description: "Approve in your Selcom Pesa app" },
  { icon: "qr_code_scanner", label: "Scan QR / TanQR", description: "Scan with any supported payment app" },
];

const STATUSES: Array<{ label: string; tone: string }> = [
  { label: "Active", tone: "bg-primary-container/10 text-primary" },
  { label: "Paid", tone: "bg-primary text-on-primary" },
  { label: "Expired", tone: "bg-surface-container-highest text-on-surface-variant" },
  { label: "Cancelled", tone: "bg-red-100 text-red-700" },
];

export default function PaymentLinksPage() {
  return (
    <div className="bg-surface text-on-surface antialiased">
      <Header />
      <main>
        <section className="py-16 md:py-20 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto grid md:grid-cols-2 gap-14 items-center">
            <div>
              <span className="text-xs font-semibold text-primary-container uppercase tracking-wide">Payment Links</span>
              <h1 className="text-2xl md:text-4xl font-bold mt-2 mb-4 text-on-surface tracking-tight">
                Get paid without a website or app
              </h1>
              <p className="text-base text-on-surface-variant max-w-lg mb-8">
                Create a shareable payment link in seconds — set the amount, attach a customer phone number, add a
                description, and choose when it expires. Share it however your customer prefers, and let them pick
                the payment method that works for them.
              </p>
              <div className="flex flex-wrap gap-2">
                {SHARE_CHANNELS.map((channel) => (
                  <span key={channel} className="bg-surface border border-outline-variant/50 text-on-surface-variant text-xs font-semibold px-3 py-1.5 rounded-full">
                    {channel}
                  </span>
                ))}
              </div>
            </div>

            {/* Preview: matches the real customer payment page (PaymentForm) exactly */}
            <div className="relative flex items-center justify-center py-4">
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-primary-container/15 rounded-full blur-3xl" />
              <div className="relative z-10 w-full max-w-sm bg-surface border border-outline-variant/50 rounded-2xl shadow-ambient-lg overflow-hidden">
                <div className="bg-primary p-6 text-on-primary">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-on-primary/70">Payment Request</p>
                    <span className="flex shrink-0 items-center gap-1">
                      <Icon name="all_inclusive" className="text-on-primary text-[15px]" />
                      <span className="text-xs font-bold tracking-tight text-on-primary">InfinityPay</span>
                    </span>
                  </div>
                  <p className="mt-2 text-3xl font-bold">TZS 25,000.00</p>
                  <p className="mt-2 text-sm text-on-primary/80">Web design deposit</p>
                  <p className="mt-3 text-sm text-on-primary/80">For Amani Traders Ltd · 255712345678</p>
                  <p className="mt-1 text-xs text-on-primary/70">Expires in 2 days</p>
                </div>
                <div className="p-6 space-y-2.5">
                  <p className="text-sm font-medium text-on-surface mb-1">Choose how you want to pay</p>
                  {PAYMENT_METHODS.map((method) => (
                    <div
                      key={method.label}
                      className="w-full flex items-center gap-3.5 rounded border border-outline-variant px-4 py-3.5"
                    >
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-primary">
                        <Icon name={method.icon} className="text-[19px]" />
                      </span>
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm font-semibold text-on-surface">{method.label}</span>
                        <span className="block text-xs text-on-surface-variant">{method.description}</span>
                      </span>
                      <Icon name="chevron_right" className="text-[16px] text-on-surface-variant shrink-0" />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading eyebrow="Creating a Link" title="What Goes Into a Payment Link" description="Every payment link carries everything the customer needs to pay with confidence." />
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-6 mt-10">
              {CREATE_FIELDS.map((field) => (
                <div key={field.label} className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl p-6">
                  <Icon name={field.icon} className="text-primary-container text-[26px] mb-3 block" />
                  <h3 className="text-sm font-bold text-on-surface mb-1.5">{field.label}</h3>
                  <p className="text-sm text-on-surface-variant leading-relaxed">{field.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto text-center">
            <SectionHeading eyebrow="Link Status" title="Track Every Link From Creation to Payment" description="Every payment link moves through a clear lifecycle so you always know where it stands." />
            <div className="flex flex-wrap justify-center gap-3 mt-8">
              {STATUSES.map((status) => (
                <span key={status.label} className={`px-4 py-2 rounded-full text-sm font-semibold ${status.tone}`}>
                  {status.label}
                </span>
              ))}
            </div>
          </div>
        </section>

        <CTASection
          title="Create your first payment link"
          description="Tell us about your business and start sharing payment links with your customers."
          primaryLabel="Create Payment Link"
          primaryHref="/create-account"
          secondaryLabel="View API Docs"
          secondaryHref="/api-docs"
        />
      </main>
      <Footer />
    </div>
  );
}
