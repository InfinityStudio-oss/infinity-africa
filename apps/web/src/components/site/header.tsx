"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Icon } from "@/components/portal/icon";

export const NAV_LINKS = [
  { href: "/", label: "Home" },
  { href: "/solutions", label: "Solutions" },
  { href: "/payment-links", label: "Payment Links" },
  { href: "/invoices", label: "Invoices" },
  { href: "/api-docs", label: "API Docs" },
  { href: "/contact", label: "Contact" },
];

export function Header() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  return (
    <header className="bg-surface/90 backdrop-blur-sm sticky top-0 z-50 border-b border-outline-variant/60 w-full">
      <div className="flex justify-between items-center px-4 md:px-10 py-4 max-w-[1280px] mx-auto">
        <Link href="/" className="flex items-center">
          <span className="text-xl font-bold tracking-tight text-primary">InfinityPay</span>
        </Link>
        <nav className="hidden lg:flex items-center gap-7">
          {NAV_LINKS.map((link) => {
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={
                  isActive
                    ? "text-primary font-bold border-b-2 border-primary pb-1 text-sm"
                    : "text-on-surface-variant font-medium text-sm hover:text-primary transition-colors duration-200"
                }
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-3">
          <Link
            href="/merchant/login"
            className="hidden lg:inline-flex text-on-surface-variant font-medium text-sm hover:text-primary transition-colors duration-200"
          >
            Sign in
          </Link>
          <Link
            href="/create-account"
            className="hidden lg:inline-flex bg-primary-container text-on-primary text-sm font-medium px-6 py-2.5 rounded-lg hover:opacity-90 transition-opacity shadow-ambient"
          >
            Get Started
          </Link>
          <button
            onClick={() => setOpen((prev) => !prev)}
            aria-label="Toggle navigation menu"
            className="lg:hidden text-primary p-1"
          >
            <Icon name={open ? "close" : "menu"} className="text-[28px]" />
          </button>
        </div>
      </div>
      {open && (
        <div className="lg:hidden border-t border-outline-variant/60 bg-surface px-4 py-4 flex flex-col gap-1">
          {NAV_LINKS.map((link) => {
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className={isActive ? "py-2.5 text-primary font-bold text-sm" : "py-2.5 text-on-surface-variant font-medium text-sm"}
              >
                {link.label}
              </Link>
            );
          })}
          <Link
            href="/merchant/login"
            onClick={() => setOpen(false)}
            className="py-2.5 text-on-surface-variant font-medium text-sm"
          >
            Sign in
          </Link>
          <Link
            href="/create-account"
            onClick={() => setOpen(false)}
            className="mt-2 bg-primary-container text-on-primary text-sm font-medium px-6 py-3 rounded-lg text-center"
          >
            Get Started
          </Link>
        </div>
      )}
    </header>
  );
}
