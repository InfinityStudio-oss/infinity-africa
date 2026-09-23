"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isPathAllowedForRole } from "@/lib/portal/roles";

import { Icon } from "./icon";
import { PORTAL_NAV_ITEMS } from "./nav-items";
import { useRole } from "./role-context";

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const { role } = useRole();
  const visibleNavItems = PORTAL_NAV_ITEMS.filter((item) => isPathAllowedForRole(role, item.href));

  return (
    <>
      {open && (
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/40 z-40 md:hidden"
          aria-hidden
        />
      )}
      <aside
        className={`fixed left-0 top-0 h-full w-64 bg-gradient-to-b from-sidebar to-sidebar-strong shadow-lg z-50 flex flex-col py-8 px-4 overflow-y-auto transition-transform duration-200 md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="mb-5 flex items-center gap-3 px-4 shrink-0">
          <Link href="/dashboard/overview" className="flex items-center flex-1 min-w-0">
            <span className="text-xl font-bold text-white tracking-tight truncate">InfinityPay</span>
          </Link>
          <button onClick={onClose} className="md:hidden text-sidebar-text p-1" aria-label="Close menu">
            <Icon name="close" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5">
          {visibleNavItems.map((item) => {
            const isActive =
              item.href === "/dashboard/overview" ? pathname === "/dashboard/overview" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                className={
                  isActive
                    ? "flex items-center gap-2.5 px-4 py-2 rounded-lg bg-sidebar-active-bg text-sidebar-active-text font-bold text-sm shadow-sm"
                    : "flex items-center gap-2.5 px-4 py-2 rounded-lg text-sidebar-text/90 hover:bg-sidebar-hover hover:text-white transition-colors text-sm font-medium"
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
