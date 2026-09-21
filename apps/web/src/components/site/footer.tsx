import Link from "next/link";

import { Icon } from "@/components/portal/icon";

const QUICK_LINKS = [
  { href: "/", label: "Home" },
  { href: "/solutions", label: "Solutions" },
  { href: "/payment-links", label: "Payment Links" },
  { href: "/invoices", label: "Invoices" },
  { href: "/contact", label: "Contact" },
  { href: "/create-account", label: "Get Started" },
  { href: "/report-transaction", label: "Report Transaction" },
];

const DEVELOPER_LINKS = [
  { href: "/api-docs", label: "API Docs Overview" },
  { href: "/developers/authentication", label: "API Key Authentication" },
  { href: "/developers/webhooks", label: "Webhooks" },
  { href: "/developers/sandbox", label: "Sandbox Examples" },
];

export function Footer() {
  return (
    <footer className="bg-primary border-t border-on-primary/10 w-full">
      <div className="py-16 px-4 md:px-10 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-10 max-w-[1280px] mx-auto">
        <div className="col-span-1 lg:col-span-1">
          <div className="inline-flex items-center gap-1.5 mb-4">
            <Icon name="all_inclusive" className="text-on-primary text-[24px]" />
            <span className="text-lg font-bold tracking-tight text-on-primary">InfinityPay</span>
          </div>
          <p className="text-base text-on-primary/80 max-w-sm">
            Secure payment infrastructure for growing merchants — collect, link, invoice, and integrate from one
            platform.
          </p>
        </div>
        <div>
          <h4 className="text-xs font-semibold text-on-primary uppercase tracking-wider mb-4">Quick Links</h4>
          <ul className="space-y-3">
            {QUICK_LINKS.map((link) => (
              <li key={link.href}>
                <Link className="text-base text-on-primary/80 hover:text-on-primary transition-colors" href={link.href}>
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-semibold text-on-primary uppercase tracking-wider mb-4">Developer</h4>
          <ul className="space-y-3">
            {DEVELOPER_LINKS.map((link) => (
              <li key={link.href}>
                <Link className="text-base text-on-primary/80 hover:text-on-primary transition-colors" href={link.href}>
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-semibold text-on-primary uppercase tracking-wider mb-4">Contact</h4>
          {/* These addresses use the domain currently verified for mail
              (see docs/email-delivery.md) — not necessarily the same
              domain the site itself is served from below. */}
          <ul className="space-y-4">
            <li className="flex items-start gap-2.5">
              <Icon name="mail" className="text-[18px] text-on-primary/70 mt-0.5" />
              <a className="text-base text-on-primary/90 hover:text-on-primary transition-colors" href="mailto:info@infinityafrica.net">
                info@infinityafrica.net
              </a>
            </li>
            <li className="flex items-start gap-2.5">
              <Icon name="support_agent" className="text-[18px] text-on-primary/70 mt-0.5" />
              <a className="text-base text-on-primary/90 hover:text-on-primary transition-colors" href="mailto:help@infinityafrica.net">
                help@infinityafrica.net
              </a>
            </li>
            <li className="flex items-start gap-2.5">
              <Icon name="headset_mic" className="text-[18px] text-on-primary/70 mt-0.5" />
              <a className="text-base text-on-primary/90 hover:text-on-primary transition-colors" href="mailto:info@infinityafrica.net">
                info@infinityafrica.net
              </a>
            </li>
            <li className="flex items-start gap-2.5">
              <Icon name="call" className="text-[18px] text-on-primary/70 mt-0.5" />
              <a className="text-base text-on-primary/90 hover:text-on-primary transition-colors" href="https://wa.me/255747730270">
                +255 747 730 270
              </a>
            </li>
            <li className="flex items-start gap-2.5">
              <Icon name="language" className="text-[18px] text-on-primary/70 mt-0.5" />
              <a className="text-base text-on-primary/90 hover:text-on-primary transition-colors" href="https://infinitypay.me">
                infinitypay.me
              </a>
            </li>
            <li className="flex items-start gap-2.5">
              <Icon name="location_on" className="text-[18px] text-on-primary/70 mt-0.5 shrink-0" />
              <span className="text-sm text-on-primary/90 whitespace-nowrap">Mbezi Luis - Ubungo - Dar es Salaam</span>
            </li>
          </ul>
        </div>
      </div>
      <div className="border-t border-on-primary/10 py-5 px-4 md:px-10">
        <div className="max-w-[1280px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
          <p className="text-xs font-semibold text-on-primary/70">© {new Date().getFullYear()} InfinityPay. All rights reserved.</p>
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
