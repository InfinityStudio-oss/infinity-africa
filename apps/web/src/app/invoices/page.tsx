import { Icon } from "@/components/portal/icon";
import { CTASection } from "@/components/site/cta-section";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { SectionHeading } from "@/components/site/section-heading";

export const metadata = {
  title: "Invoices | InfinityPay",
  description: "Create professional invoices with itemized line items, due dates, and a built-in Pay Now link so customers can settle instantly.",
};

const INVOICE_FIELDS = [
  { icon: "person", label: "Customer Details", description: "Add the customer's name, phone, and email so invoices reach the right person." },
  { icon: "list_alt", label: "Items / Services", description: "Break the invoice into line items with quantity and unit price." },
  { icon: "event", label: "Due Date", description: "Set a due date so customers know exactly when payment is expected." },
  { icon: "link", label: "Pay Now Link", description: "Every invoice ships with a built-in payment link so customers can settle instantly." },
];

const STATUSES: Array<{ label: string; tone: string }> = [
  { label: "Draft", tone: "bg-surface-container-highest text-on-surface-variant" },
  { label: "Sent", tone: "bg-blue-100 text-blue-700" },
  { label: "Paid", tone: "bg-primary text-on-primary" },
  { label: "Partially Paid", tone: "bg-amber-100 text-amber-700" },
  { label: "Overdue", tone: "bg-red-100 text-red-700" },
  { label: "Cancelled", tone: "bg-surface-container-highest text-on-surface-variant" },
];

const LINE_ITEMS = [
  { description: "Website design deposit", qty: 1, price: "150,000", total: "150,000" },
  { description: "Hosting setup", qty: 1, price: "35,000", total: "35,000" },
];

export default function InvoicesPage() {
  return (
    <div className="bg-surface text-on-surface antialiased">
      <Header />
      <main>
        <section className="py-16 md:py-20 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto grid md:grid-cols-2 gap-14 items-center">
            <div>
              <span className="text-xs font-semibold text-primary-container uppercase tracking-wide">Invoices</span>
              <h1 className="text-2xl md:text-4xl font-bold mt-2 mb-4 text-on-surface tracking-tight">
                Professional invoices customers can pay instantly
              </h1>
              <p className="text-base text-on-surface-variant max-w-lg">
                Build an itemized invoice with customer details, line items, and a due date — every invoice includes a
                Pay Now link so your customer can settle it the moment they open it, with no back-and-forth.
              </p>
            </div>

            {/* Preview: invoice card */}
            <div className="relative flex items-center justify-center py-4">
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-primary-container/15 rounded-full blur-3xl" />
              <div className="relative z-10 w-full max-w-sm bg-surface border border-outline-variant/50 rounded-2xl shadow-ambient-lg overflow-hidden">
                <div className="p-6 border-b border-outline-variant/40">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-bold text-primary">InfinityPay</span>
                    <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-blue-100 text-blue-700">Sent</span>
                  </div>
                  <p className="text-xs text-on-surface-variant">Invoice #INV-1043 · Due 24 Aug 2026</p>
                  <p className="text-xs text-on-surface-variant mt-1">Bill to: Grace Mwakalinga</p>
                </div>
                <div className="p-6 space-y-3">
                  {LINE_ITEMS.map((item) => (
                    <div key={item.description} className="flex items-center justify-between text-sm">
                      <div>
                        <p className="font-medium text-on-surface">{item.description}</p>
                        <p className="text-xs text-on-surface-variant">Qty {item.qty} · TZS {item.price}</p>
                      </div>
                      <span className="font-semibold text-on-surface">TZS {item.total}</span>
                    </div>
                  ))}
                  <div className="border-t border-outline-variant/40 pt-3 flex items-center justify-between">
                    <span className="text-sm font-semibold text-on-surface">Total Due</span>
                    <span className="text-lg font-bold text-primary-container">TZS 185,000</span>
                  </div>
                  <button className="w-full mt-2 bg-primary-container text-on-primary text-sm font-medium py-3 rounded-lg">Pay Now</button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[1280px] mx-auto">
            <SectionHeading eyebrow="Creating an Invoice" title="Everything an Invoice Needs" description="Build a complete, professional invoice in minutes." />
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-6 mt-10">
              {INVOICE_FIELDS.map((field) => (
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
            <SectionHeading eyebrow="Invoice Status" title="Track Every Invoice From Draft to Paid" description="Every invoice moves through a clear lifecycle so you always know what's outstanding." />
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
          title="Create your first invoice"
          description="Tell us about your business and start sending professional, payable invoices."
          primaryLabel="Create Invoice"
          primaryHref="/create-account"
          secondaryLabel="View API Docs"
          secondaryHref="/api-docs"
        />
      </main>
      <Footer />
    </div>
  );
}
