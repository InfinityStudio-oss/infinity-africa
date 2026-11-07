"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Icon } from "@/components/portal/icon";

import { ADMIN_NAV_SECTIONS, type AdminNavItem } from "./nav-items";

/** Dashboard is the only exact match — every other entry owns its
 * subtree, so /super-admin/notifications/email keeps Notifications lit.
 * Matching on a path *segment* rather than a raw prefix, so a future
 * /super-admin/sms-campaigns could never light up /super-admin/sms. */
function active(pathname: string, href: string): boolean {
  if (href === "/super-admin") return pathname === "/super-admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({
  item,
  pathname,
  onClose,
}: {
  item: AdminNavItem;
  pathname: string;
  onClose: () => void;
}) {
  const isActive = active(pathname, item.href);
  return (
    <div>
      <Link
        href={item.href}
        onClick={onClose}
        aria-current={isActive ? "page" : undefined}
        className={
          isActive
            ? "flex items-center gap-3 px-4 py-2.5 rounded-lg bg-sidebar-active-bg text-sidebar-active-text font-bold text-sm shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
            : "flex items-center gap-3 px-4 py-2.5 rounded-lg text-sidebar-text/90 hover:bg-sidebar-hover hover:text-white transition-colors text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        }
      >
        <Icon name={item.icon} filled={isActive} className="shrink-0" />
        {/* Wraps rather than truncates. "Webhooks & Reconciliation" and
            "Onboarding & Compliance" do not fit one line at this width,
            and an admin reading "Onboarding & Compl…" has to guess. Two
            tidy lines cost a few pixels of height; a clipped label costs
            a click to find out what it was. */}
        <span className="leading-snug">{item.label}</span>
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
                    ? "flex items-center gap-2.5 px-3 py-2 rounded-lg bg-sidebar-active-bg/70 text-sidebar-active-text font-semibold text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                    : "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sidebar-text/70 hover:bg-sidebar-hover hover:text-white transition-colors text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                }
              >
                {/* text-[18px] used to sit here and never applied —
                    Google's stylesheet overrode it. admin-nav-icon-nested
                    is the rule that actually lands. */}
                <Icon name={child.icon} filled={childActive} className="shrink-0 admin-nav-icon-nested" />
                <span className="leading-snug">{child.label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function AdminSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();

  return (
    <>
      {open && <div onClick={onClose} className="fixed inset-0 bg-black/40 z-40 md:hidden" aria-hidden />}
      <aside
        className={`fixed left-0 top-0 h-full w-64 bg-gradient-to-b from-sidebar to-sidebar-strong shadow-lg z-50 flex flex-col py-8 overflow-hidden transition-transform duration-200 md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="mb-6 flex items-center gap-3 px-8 shrink-0">
          <Link href="/super-admin" className="flex items-center flex-1 min-w-0">
            <span className="text-xl font-bold text-white tracking-tight truncate">InfinityPay</span>
          </Link>
          <button onClick={onClose} className="md:hidden text-sidebar-text p-1" aria-label="Close menu">
            <Icon name="close" />
          </button>
        </div>

        {/* The scroll lives here, not on the aside, so the wordmark stays
            put and — more to the point — Settings and Audit Logs stay
            reachable on a short laptop screen or a phone in landscape,
            where six headings plus eighteen links are taller than the
            viewport. min-h-0 is what actually lets a flex child shrink
            enough to scroll. */}
        {/* admin-sidebar-nav carries the icon sizing (app/globals.css) —
            it cannot be done with a utility class on the span, see the
            comment there. */}
        <nav className="admin-sidebar-nav flex-1 min-h-0 overflow-y-auto px-4 space-y-5">
          {ADMIN_NAV_SECTIONS.map((section) => {
            // A heading with nothing under it is noise. Nothing filters
            // these today — the whole area sits behind requireSuperAdmin
            // — but if a link ever becomes conditional, the heading goes
            // with it rather than being left pointing at empty space.
            if (section.items.length === 0) return null;
            return (
              <div key={section.heading}>
                <h2 className="px-4 mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-sidebar-text-muted">
                  {section.heading}
                </h2>
                <div className="space-y-0.5">
                  {section.items.map((item) => (
                    <NavLink key={item.href} item={item} pathname={pathname} onClose={onClose} />
                  ))}
                </div>
              </div>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
