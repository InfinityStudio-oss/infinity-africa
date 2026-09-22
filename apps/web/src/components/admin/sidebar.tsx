"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Icon } from "@/components/portal/icon";

import { ADMIN_NAV_ITEMS } from "./nav-items";

export function AdminSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();

  return (
    <>
      {open && <div onClick={onClose} className="fixed inset-0 bg-black/40 z-40 md:hidden" aria-hidden />}
      <aside
        className={`fixed left-0 top-0 h-full w-64 bg-gradient-to-b from-sidebar to-sidebar-strong shadow-lg z-50 flex flex-col py-8 px-4 overflow-y-auto transition-transform duration-200 md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="mb-8 flex items-center gap-3 px-4 shrink-0">
          <Link href="/super-admin" className="flex flex-col gap-1 flex-1 min-w-0">
            <span className="flex items-center">
              <span className="text-xl font-bold text-white tracking-tight truncate">InfinityPay</span>
            </span>
            <p className="text-[11px] font-semibold tracking-wide text-sidebar-text-muted">
              Super Admin
            </p>
          </Link>
          <button onClick={onClose} className="md:hidden text-sidebar-text p-1" aria-label="Close menu">
            <Icon name="close" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5">
          {ADMIN_NAV_ITEMS.map((item) => {
            const isActive = item.href === "/super-admin" ? pathname === "/super-admin" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                className={
                  isActive
                    ? "flex items-center gap-3 px-4 py-2.5 rounded-lg bg-sidebar-active-bg text-sidebar-active-text font-bold text-sm shadow-sm"
                    : "flex items-center gap-3 px-4 py-2.5 rounded-lg text-sidebar-text/90 hover:bg-sidebar-hover hover:text-white transition-colors text-sm font-medium"
                }
              >
                <Icon name={item.icon} filled={isActive} className="shrink-0" />
                <span className="truncate">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
