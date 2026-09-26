"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { LogOutButton } from "@/components/auth/log-out-button";
import { merchantLogout } from "@/lib/supabase/logout";
import { getMyMembership } from "@/lib/portal/api";
import { MERCHANT_ROLES, USER_ROLE_LABELS } from "@/lib/portal/roles";
import type { MerchantUser } from "@/lib/portal/types";

import { Icon } from "./icon";
import { useRole } from "./role-context";

function initials(name: string | null, email: string | null): string {
  if (name) {
    const parts = name.split(" ").filter(Boolean);
    return parts
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase();
  }
  return email ? email[0].toUpperCase() : "?";
}

const SUPPORT_EMAIL = "info@infinitypay.me";

export function Topbar({ onOpenSidebar }: { onOpenSidebar: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [emailCopied, setEmailCopied] = useState(false);
  const [profile, setProfile] = useState<MerchantUser | null>(null);
  const { role, setRole } = useRole();

  async function handleCopySupportEmail() {
    try {
      await navigator.clipboard.writeText(SUPPORT_EMAIL);
      setEmailCopied(true);
      setTimeout(() => setEmailCopied(false), 2000);
    } catch {
      // Clipboard API unavailable (e.g. insecure context) — the email is
      // still visible and selectable in the popover text itself.
    }
  }

  useEffect(() => {
    getMyMembership().then(setProfile);
  }, []);

  return (
    <header className="fixed top-0 right-0 w-full md:w-[calc(100%-16rem)] z-30 bg-surface/80 backdrop-blur-md shadow-sm flex justify-between items-center h-16 px-4 md:px-8 border-b border-surface-container-highest">
      <div className="flex items-center gap-4 flex-1">
        <button
          onClick={onOpenSidebar}
          className="md:hidden text-on-surface-variant p-2 -ml-2 rounded-lg hover:bg-surface-container-highest"
          aria-label="Open menu"
        >
          <Icon name="menu" />
        </button>
        <div className="relative w-full max-w-md hidden sm:block">
          <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-outline" />
          <input
            className="w-full pl-10 pr-4 py-2 bg-surface-container-low border border-surface-container-highest rounded-lg focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary text-sm text-on-surface placeholder-outline transition-all"
            placeholder="Search transactions, invoices, payment links..."
            type="text"
          />
        </div>
      </div>
      <div className="flex items-center gap-2 md:gap-4">
        <label className="hidden md:flex items-center gap-2 text-xs font-semibold text-on-surface-variant">
          Role
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as typeof role)}
            className="bg-surface-container-low border border-surface-container-highest rounded-lg text-xs font-semibold text-on-surface px-2.5 py-1.5 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary"
            aria-label="Switch role"
          >
            {MERCHANT_ROLES.map((option) => (
              <option key={option} value={option}>
                {USER_ROLE_LABELS[option]}
              </option>
            ))}
          </select>
        </label>
        <Link
          href="/dashboard/pay-by-link"
          className="hidden lg:flex items-center gap-2 bg-primary-container text-on-primary px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <Icon name="add" className="text-[20px]" />
          New Pay by Link
        </Link>
        <div className="relative hidden sm:block">
          <button
            onClick={() => setHelpOpen((open) => !open)}
            className="p-2 text-on-surface-variant hover:bg-surface-container-high transition-colors rounded-full"
            aria-label="Help"
            title="Help"
          >
            <Icon name="help_outline" />
          </button>
          {helpOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setHelpOpen(false)} aria-hidden />
              <div className="absolute right-0 top-11 z-50 w-72 bg-surface border border-surface-container-highest rounded-lg shadow-ambient overflow-hidden">
                <div className="px-4 py-3 border-b border-surface-container-highest">
                  <p className="text-sm font-semibold text-on-background">Need help?</p>
                  <p className="text-xs text-on-surface-variant mt-0.5">Reach the InfinityPay team directly.</p>
                </div>
                <div className="p-4 space-y-3">
                  <div className="flex items-center justify-between gap-2 bg-surface-container-low border border-surface-container-highest rounded-lg px-3 py-2.5">
                    <span className="text-sm text-on-surface truncate">{SUPPORT_EMAIL}</span>
                    <button
                      type="button"
                      onClick={handleCopySupportEmail}
                      className="shrink-0 p-1.5 text-primary hover:bg-primary-container/10 rounded-md transition-colors"
                      title="Copy email"
                    >
                      <Icon name={emailCopied ? "check" : "content_copy"} className="text-[18px]" />
                    </button>
                  </div>
                  {emailCopied && <p className="text-xs font-medium text-primary">Copied!</p>}
                  <a
                    href={`mailto:${SUPPORT_EMAIL}`}
                    className="block text-center bg-primary-container text-on-primary text-sm font-medium py-2.5 rounded-lg hover:opacity-90 transition-opacity"
                  >
                    Open in email app
                  </a>
                </div>
              </div>
            </>
          )}
        </div>
        <div className="relative ml-2">
          <button
            onClick={() => setMenuOpen((open) => !open)}
            className="w-9 h-9 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-sm border border-outline-variant shrink-0"
            aria-label="Account menu"
          >
            {initials(profile?.full_name ?? null, profile?.email ?? null)}
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} aria-hidden />
              <div className="absolute right-0 top-11 z-50 w-64 bg-surface border border-surface-container-highest rounded-lg shadow-ambient overflow-hidden">
                <div className="px-4 py-3 border-b border-surface-container-highest">
                  <p className="text-sm font-semibold text-on-background truncate">
                    {profile?.full_name ?? "Signed in"}
                  </p>
                  <p className="text-xs text-on-surface-variant truncate">{profile?.email ?? ""}</p>
                  {profile && (
                    <span className="inline-block mt-1.5 text-[11px] font-semibold bg-primary-container/10 text-primary px-2 py-0.5 rounded-full">
                      {USER_ROLE_LABELS[profile.role]}
                    </span>
                  )}
                </div>
                <Link
                  href="/dashboard/profile"
                  onClick={() => setMenuOpen(false)}
                  className="block px-4 py-2.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
                >
                  Profile &amp; Settings
                </Link>
                <form action={merchantLogout}>
                  <LogOutButton className="w-full text-left px-4 py-2.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors disabled:cursor-not-allowed disabled:opacity-60" />
                </form>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
