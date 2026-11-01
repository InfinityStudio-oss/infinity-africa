"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Icon } from "@/components/portal/icon";

import { ADMIN_NAV_ITEMS } from "./nav-items";

/** Dashboard is the only exact match — every other entry owns its
 * subtree, so /super-admin/notifications/email keeps Notifications lit.
 * Matching on a path *segment* rather than a raw prefix, so a future
 * /super-admin/sms-campaigns could never light up /super-admin/sms. */
function active(pathname: string, href: string): boolean {
  if (href === "/super-admin") return pathname === "/super-admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();

  return (
    <>
      {open && <div onClick={onClose} className="fixed inset-0 bg-black/40 z-40 md:hidden" aria-hidden />}
      <aside
        className={`fixed left-0 top-0 h-full w-64 bg-gradient-to-b from-sidebar to-sidebar-strong shadow-lg z-50 flex flex-col py-8 px-4 overflow-y-auto transition-transform duration-200 md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="mb-8 flex items-center gap-3 px-4 shrink-0">
          <Link href="/super-admin" className="flex items-center flex-1 min-w-0">
            <span className="text-xl font-bold text-white tracking-tight truncate">InfinityPay</span>
          </Link>
          <button onClick={onClose} className="md:hidden text-sidebar-text p-1" aria-label="Close menu">
            <Icon name="close" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5">
          {ADMIN_NAV_ITEMS.map((item) => {
            const isActive = active(pathname, item.href);
            return (
              <div key={item.href}>
                <Link
                  href={item.href}
                  onClick={onClose}
                  aria-current={isActive ? "page" : undefined}
                  className={
                    isActive
                      ? "flex items-center gap-3 px-4 py-2.5 rounded-lg bg-sidebar-active-bg text-sidebar-active-text font-bold text-sm shadow-sm"
                      : "flex items-center gap-3 px-4 py-2.5 rounded-lg text-sidebar-text/90 hover:bg-sidebar-hover hover:text-white transition-colors text-sm font-medium"
                  }
                >
                  <Icon name={item.icon} filled={isActive} className="shrink-0" />
                  <span className="truncate">{item.label}</span>
                </Link>
                {/* Children show only while their section is open, so the
                    sidebar does not grow a permanent indented block for a
                    page nobody is on. */}
                {item.children && isActive && (
                  <div className="mt-0.5 space-y-0.5 pl-7">
                    {item.children.map((child) => {
                      const childActive = active(pathname, child.href);
                      return (
                        <Link
                          key={child.href}
                          href={child.href}
                          onClick={onClose}
                          aria-current={childActive ? "page" : undefined}
                          className={
                            childActive
                              ? "flex items-center gap-2.5 px-3 py-2 rounded-lg bg-sidebar-active-bg/70 text-sidebar-active-text font-semibold text-sm"
                              : "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sidebar-text/70 hover:bg-sidebar-hover hover:text-white transition-colors text-sm"
                          }
                        >
                          <Icon name={child.icon} filled={childActive} className="shrink-0 text-[18px]" />
                          <span className="truncate">{child.label}</span>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
