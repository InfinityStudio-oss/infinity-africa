"use client";

import Link from "next/link";
import { useState } from "react";

import { Icon } from "@/components/portal/icon";
import { adminLogout } from "@/lib/supabase/logout";

function initials(name: string | null, email: string): string {
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

export function AdminTopbar({
  onOpenSidebar,
  notificationCount = 0,
  adminEmail = "",
  adminFullName = null,
}: {
  onOpenSidebar: () => void;
  notificationCount?: number;
  adminEmail?: string;
  adminFullName?: string | null;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

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
        <div className="flex-1 max-w-xl hidden sm:flex items-center bg-surface-container-low rounded-full px-4 py-2 border border-outline-variant focus-within:border-primary transition-colors">
          <Icon name="search" className="text-on-surface-variant mr-2 text-[20px]" />
          <input
            className="bg-transparent border-none outline-none w-full text-sm text-on-surface focus:ring-0 placeholder:text-on-surface-variant p-0"
            placeholder="Search businesses, transactions, invoices..."
            type="text"
          />
        </div>
      </div>
      <div className="flex items-center gap-1 md:gap-3">
        <button className="text-on-surface-variant hover:bg-surface-container-high transition-colors p-2 rounded-full relative" aria-label="Notifications">
          <Icon name="notifications" />
          {notificationCount > 0 && (
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-error rounded-full border-2 border-surface" />
          )}
        </button>
        <button className="text-on-surface-variant hover:bg-surface-container-high transition-colors p-2 rounded-full hidden sm:block">
          <Icon name="help_outline" />
        </button>
        <div className="relative flex items-center gap-2 pl-2 md:pl-4 md:border-l border-outline-variant">
          <button
            onClick={() => setMenuOpen((open) => !open)}
            className="flex items-center gap-2"
            aria-label="Account menu"
          >
            <div className="w-8 h-8 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-sm border border-outline-variant shrink-0">
              {initials(adminFullName, adminEmail)}
            </div>
            <span className="text-sm font-medium text-on-surface hidden lg:block truncate max-w-[140px]">
              {adminFullName ?? adminEmail ?? "Super Admin"}
            </span>
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} aria-hidden />
              <div className="absolute right-0 top-11 z-50 w-64 bg-surface border border-surface-container-highest rounded-lg shadow-ambient overflow-hidden">
                <div className="px-4 py-3 border-b border-surface-container-highest">
                  <p className="text-sm font-semibold text-on-background truncate">{adminFullName ?? "Signed in"}</p>
                  <p className="text-xs text-on-surface-variant truncate">{adminEmail}</p>
                  <span className="inline-block mt-1.5 text-[11px] font-semibold bg-primary-container/10 text-primary px-2 py-0.5 rounded-full">
                    Super Admin
                  </span>
                </div>
                <Link
                  href="/super-admin/profile"
                  onClick={() => setMenuOpen(false)}
                  className="block px-4 py-2.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
                >
                  Profile
                </Link>
                <Link
                  href="/super-admin/settings"
                  onClick={() => setMenuOpen(false)}
                  className="block px-4 py-2.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
                >
                  Change Password
                </Link>
                <form action={adminLogout}>
                  <button
                    type="submit"
                    className="w-full text-left px-4 py-2.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
                  >
                    Log out
                  </button>
                </form>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
