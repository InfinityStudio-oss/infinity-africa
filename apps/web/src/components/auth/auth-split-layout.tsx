import Link from "next/link";

import { Icon } from "@/components/portal/icon";

/**
 * Shared two-panel layout for the standalone auth pages (/login,
 * /dashboard/login, /create-account): a brand panel on the left (hidden on
 * small screens, where the card alone carries the page) and the page's own
 * card on the right.
 */
export function AuthSplitLayout({
  children,
  maxWidthClassName = "max-w-sm",
}: {
  children: React.ReactNode;
  maxWidthClassName?: string;
}) {
  return (
    <div className="flex flex-1 min-h-full">
      <div className="hidden lg:flex lg:w-[52%] relative flex-col justify-center overflow-hidden bg-primary text-on-primary p-8">
        <div className="absolute -top-24 -right-24 w-72 h-72 rounded-full bg-on-primary/5" aria-hidden />
        <div className="absolute bottom-10 left-10 w-80 h-80 rounded-full bg-on-primary/5" aria-hidden />

        <div className="absolute top-8 left-8 z-10">
          <Link href="/" className="inline-flex items-center">
            <span className="text-lg font-bold tracking-tight text-on-primary">InfinityPay</span>
          </Link>
        </div>

        <div className="relative z-10">
          <p className="text-3xl font-bold tracking-tight max-w-sm" aria-hidden>
            Welcome to InfinityPay
          </p>
          <p className="mt-4 max-w-sm text-on-primary/80 leading-relaxed">
            Payment infrastructure for growing merchants — collect, link, invoice, and integrate from one platform.
          </p>
          <p className="mt-4 max-w-sm text-on-primary/80 leading-relaxed">
            Access your merchant portal to manage payment links, invoices, transactions, and API integration.
          </p>
        </div>

        <div className="relative z-10 space-y-4 mt-16">
          <p className="text-xs font-semibold uppercase tracking-wide text-on-primary/70">Need Assistance?</p>
          <ul className="space-y-2.5 text-sm text-on-primary/90">
            <li className="flex items-center gap-2.5">
              <Icon name="mail" className="text-[18px] text-on-primary/70" />
              <a href="mailto:help@infinitypay.me" className="hover:text-on-primary transition-colors">
                help@infinitypay.me
              </a>
            </li>
            <li className="flex items-center gap-2.5">
              <Icon name="mail" className="text-[18px] text-on-primary/70" />
              <a href="mailto:info@infinitypay.me" className="hover:text-on-primary transition-colors">
                info@infinitypay.me
              </a>
            </li>
            <li className="flex items-center gap-2.5">
              <Icon name="call" className="text-[18px] text-on-primary/70" />
              <a href="https://wa.me/255747730270" className="hover:text-on-primary transition-colors">
                +255 747 730 270
              </a>
            </li>
            <li className="flex items-center gap-2.5">
              <Icon name="location_on" className="text-[18px] text-on-primary/70" />
              Mbezi - Ubungo - Dar es Salaam
            </li>
          </ul>
          <p className="pt-4 border-t border-on-primary/10 text-xs text-on-primary/60">
            © {new Date().getFullYear()} InfinityPay. All rights reserved.
          </p>
        </div>
      </div>

      <div className="flex flex-1 items-center justify-center bg-surface-container px-4 py-16 xl:pl-8 xl:pr-16">
        <div className={`w-full ${maxWidthClassName}`}>
          <Link
            href="/"
            className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-on-surface-variant hover:text-primary transition-colors"
          >
            <Icon name="arrow_back" className="text-[18px]" />
            Back to website
          </Link>
          <div className="mb-6 flex items-center lg:hidden">
            <span className="text-lg font-bold tracking-tight text-primary">InfinityPay</span>
          </div>
          <div className="rounded-lg border border-outline-variant bg-surface p-8 shadow-sm">{children}</div>
        </div>
      </div>
    </div>
  );
}
