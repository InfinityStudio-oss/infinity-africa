import Link from "next/link";

import { Icon } from "@/components/portal/icon";

/**
 * Arranged to match infinityradius.com's footer: a brand column that
 * carries the description AND the contact details, followed by three
 * columns of links.
 *
 * The contact block used to be the fourth column. Moving it under the
 * description is the whole point of the change — it puts the ways to
 * reach a human beside the name of the company rather than at the far
 * end of a row of navigation, and it frees the fourth column for links.
 *
 * Every link here points at a route that exists. The sister site's
 * footer has "About Us" and "Support" entries; InfinityPay has no such
 * pages, so this does not borrow those labels — a footer link to a 404
 * is worse than a shorter footer.
 */

const COMPANY_LINKS = [
  { href: "/contact", label: "Contact Us" },
  { href: "/report-transaction", label: "Report Transaction" },
  { href: "/privacy", label: "Privacy Policy" },
  { href: "/terms", label: "Terms of Service" },
];

const QUICK_LINKS = [
  { href: "/", label: "Home" },
  { href: "/solutions", label: "Solutions" },
  { href: "/payment-links", label: "Pay by Link" },
  { href: "/invoices", label: "Invoices" },
  { href: "/create-account", label: "Get Started" },
  { href: "/dashboard/login", label: "Sign In" },
];

const DEVELOPER_LINKS = [
  { href: "/api-docs", label: "API Docs Overview" },
  { href: "/developers/authentication", label: "API Key Authentication" },
  { href: "/developers/webhooks", label: "Webhooks" },
  { href: "/developers/sandbox", label: "Sandbox Examples" },
];

/** These addresses use the domain currently verified for mail (see
 * docs/email-delivery.md) — not necessarily the same domain the site
 * itself is served from. */
const CONTACT_ROWS = [
  { icon: "mail", label: "info@infinitypay.me", href: "mailto:info@infinitypay.me" },
  { icon: "support_agent", label: "help@infinitypay.me", href: "mailto:help@infinitypay.me" },
  { icon: "headset_mic", label: "support@infinitypay.me", href: "mailto:support@infinitypay.me" },
  { icon: "call", label: "+255 747 730 270", href: "https://wa.me/255747730270" },
  { icon: "language", label: "infinitypay.me", href: "https://infinitypay.me" },
  { icon: "location_on", label: "Mbezi Luis - Ubungo - Dar es Salaam", href: null },
];

const linkClass = "text-base text-on-primary/80 hover:text-on-primary transition-colors";

function LinkColumn({ title, links }: { title: string; links: { href: string; label: string }[] }) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-on-primary uppercase tracking-wider mb-4">{title}</h4>
      <ul className="space-y-3">
        {links.map((link) => (
          <li key={link.href}>
            <Link className={linkClass} href={link.href}>
              {link.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Footer() {
  return (
    // The deep page base rather than the mid navy it used to be. The
    // homepage hero above it is now #071826, so a #1e3a5f footer ended
    // the page on a lighter band than the section before it. White sits
    // on this at 17.98:1.
    <footer className="bg-[#071826] border-t border-on-primary/10 w-full">
      <div className="py-16 px-4 md:px-10 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-10 lg:gap-8 max-w-[1280px] mx-auto">
        <div className="min-w-0">
          <div className="inline-flex items-center mb-4">
            <span className="text-lg font-bold tracking-tight text-on-primary">InfinityPay</span>
          </div>
          <p className="text-base text-on-primary/80 max-w-sm">
            Secure payment infrastructure for growing businesses and service providers — collect, link, invoice,
            platform.
          </p>

          <ul className="mt-6 space-y-3">
            {CONTACT_ROWS.map((row) => (
              <li key={row.label} className="flex items-start gap-2.5">
                <Icon name={row.icon} className="text-[18px] text-on-primary/70 mt-0.5 shrink-0" />
                {row.href ? (
                  <a className="text-sm text-on-primary/90 hover:text-on-primary transition-colors" href={row.href}>
                    {row.label}
                  </a>
                ) : (
                  <span className="text-sm text-on-primary/90">{row.label}</span>
                )}
              </li>
            ))}
          </ul>
        </div>

        <LinkColumn title="Company" links={COMPANY_LINKS} />
        <LinkColumn title="Quick Links" links={QUICK_LINKS} />
        <LinkColumn title="Developer" links={DEVELOPER_LINKS} />
      </div>

      <div className="border-t border-on-primary/10 py-5 px-4 md:px-10">
        <div className="max-w-[1280px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
          <p className="text-xs font-semibold text-on-primary/70">
            © {new Date().getFullYear()} InfinityPay. All rights reserved.
          </p>
          <div className="flex items-center gap-6">
            <Link href="/privacy" className="text-xs font-semibold text-on-primary/70 hover:text-on-primary transition-colors">
              Privacy Policy
            </Link>
            <Link href="/terms" className="text-xs font-semibold text-on-primary/70 hover:text-on-primary transition-colors">
              Terms of Service
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
