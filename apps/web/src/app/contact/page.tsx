import { ContactForm } from "@/components/landing/contact-form";
import { Icon } from "@/components/portal/icon";
import { ContactCard } from "@/components/site/contact-card";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";
import { SectionHeading } from "@/components/site/section-heading";

export const metadata = {
  title: "Contact | InfinityPay",
  description: "Get in touch with the InfinityPay team for integration questions, pricing, or support — for merchants and developers.",
};

export default function ContactPage() {
  return (
    <div className="bg-surface text-on-surface antialiased">
      <Header />
      <main>
        <section className="py-16 md:py-20 px-4 md:px-10 bg-surface-container-lowest">
          <div className="max-w-[1280px] mx-auto text-center">
            <SectionHeading
              eyebrow="Contact"
              title="Let's Talk"
              description="Have questions about integration, pricing, or getting your business set up? Our team in Dar es Salaam is ready to help — for merchants and developers alike."
            />
            <a
              href="mailto:info@infinityafrica.net?subject=Talk%20to%20Sales"
              className="inline-flex items-center gap-2 bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity shadow-ambient mt-8"
            >
              Talk to Sales
              <Icon name="arrow_forward" className="text-[18px]" />
            </a>
          </div>
        </section>

        <section className="py-16 px-4 md:px-10 bg-surface">
          <div className="max-w-[1280px] mx-auto grid md:grid-cols-2 gap-14">
            <div className="bg-surface border border-outline-variant/40 rounded-2xl p-8 shadow-ambient">
              <h3 className="text-2xl font-semibold text-on-surface mb-1">Send Us a Message</h3>
              <p className="text-sm text-on-surface-variant mb-6">We typically respond within one business day.</p>
              <ContactForm />
            </div>
            <div className="space-y-6">
              <div className="bg-surface-container border border-outline-variant/40 rounded-2xl p-8">
                <h3 className="text-xs font-semibold text-primary-container uppercase tracking-wide mb-6">Connect With Us</h3>
                <div className="space-y-5">
                  <ContactCard icon="mail" label="Business Email" value="info@infinityafrica.net" href="mailto:info@infinityafrica.net" />
                  <ContactCard icon="support_agent" label="Help" value="help@infinityafrica.net" href="mailto:help@infinityafrica.net" />
                  <ContactCard icon="headset_mic" label="Support" value="info@infinityafrica.net" href="mailto:info@infinityafrica.net" />
                  <ContactCard icon="call" label="Phone / WhatsApp" value="+255 747 730 270" href="https://wa.me/255747730270" />
                  <ContactCard icon="location_on" label="Location" value="Mbezi Luis - Ubungo - Dar es Salaam" />
                </div>
              </div>
              <div className="bg-gradient-to-br from-primary-container/5 to-surface-container-lowest border border-primary-container/15 rounded-2xl p-8">
                <div className="flex items-start gap-3 mb-3">
                  <Icon name="storefront" className="text-primary-container text-[24px]" />
                  <div>
                    <h4 className="text-sm font-bold text-on-surface">For Merchants</h4>
                    <p className="text-sm text-on-surface-variant mt-1">
                      Questions about collections, payment links, invoices, or withdrawals — our support team can
                      help you get set up and stay running.
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Icon name="code" className="text-primary-container text-[24px]" />
                  <div>
                    <h4 className="text-sm font-bold text-on-surface">For Developers</h4>
                    <p className="text-sm text-on-surface-variant mt-1">
                      Need help with the API, webhooks, or sandbox testing? Reach out and our developer support team
                      will get back to you.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
