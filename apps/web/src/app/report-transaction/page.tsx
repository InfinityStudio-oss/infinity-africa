import { ReportTransactionForm } from "@/components/site/report-transaction-form";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { SectionHeading } from "@/components/site/section-heading";

export const metadata = {
  title: "Report a Transaction | InfinityPay",
  description:
    "Report a chargeback or an issue with a product or service purchased through InfinityPay — InfinityPay will review the transaction and contact the merchant where necessary.",
};

export default function ReportTransactionPage() {
  return (
    <div className="bg-surface text-on-surface antialiased">
      <Header />
      <main>
        <section className="py-16 md:py-20 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[720px] mx-auto text-center">
            <SectionHeading
              eyebrow="Customer Support"
              title="Report a Transaction"
              description="If you paid a business through InfinityPay and something went wrong — a product or service you didn't receive, an unauthorized payment, or a duplicate charge — let us know and we'll review it."
            />
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[720px] mx-auto bg-surface border border-outline-variant/40 rounded-2xl p-8 shadow-ambient">
            <ReportTransactionForm />
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
