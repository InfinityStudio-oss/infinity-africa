"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isPathAllowedForRole } from "@/lib/portal/roles";

import { Icon } from "./icon";
import { PORTAL_NAV_GROUPS } from "./nav-items";
import { useRole } from "./role-context";

export function Sidebar({
  open,
  onClose,
  verified = true,
}: {
  open: boolean;
  onClose: () => void;
  /** Defaults to true so every existing caller behaves exactly as before;
   * only the portal layout, which knows the onboarding status, passes
   * false. */
  verified?: boolean;
}) {
  const pathname = usePathname();
  const { role } = useRole();

  // Filter first, then drop any group the filter emptied. A heading over
  // nothing is worse than no heading: it reads as a section that failed
  // to load rather than one this role has no links in.
  const visibleGroups = PORTAL_NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => isPathAllowedForRole(role, item.href)),
  })).filter((group) => group.items.length > 0);

  return (
    <>
      {open && (
        <div onClick={onClose} className="fixed inset-0 bg-black/40 z-40 md:hidden" aria-hidden />
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

        {/* portal-sidebar-nav carries the icon sizing (app/globals.css) —
            it cannot be a Tailwind utility on the span, see the comment
            on the rule for why. */}
        <nav className="portal-sidebar-nav flex-1">
          {visibleGroups.map((group, groupIndex) => (
            <div key={group.label ?? "primary"} className={groupIndex === 0 ? "" : "mt-5"}>
              {group.label && (
                <h2 className="px-4 mb-1 text-[11px] font-semibold uppercase tracking-wider text-sidebar-text/45">
                  {group.label}
                </h2>
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const isActive =
                    item.href === "/dashboard/overview"
                      ? pathname === "/dashboard/overview"
                      : pathname.startsWith(item.href);

                  // These pages call requireVerifiedMerchant() and
                  // redirect an unverified merchant back to Overview.
                  // Rendering them as links anyway meant a click produced
                  // a blank flash and a silent bounce, which reads as the
                  // portal being broken rather than the account not being
                  // approved yet. Say so instead, and do not navigate.
                  if (item.requiresVerification && !verified) {
                    return (
                      <div
                        key={item.href}
                        title="Available once your account is verified"
                        className="flex items-center gap-2.5 px-4 py-2 rounded-lg text-sidebar-text/40 text-sm font-medium cursor-not-allowed"
                      >
                        <Icon name={item.icon} className="shrink-0" />
                        <span className="truncate flex-1">{item.label}</span>
                        <Icon name="lock" className="portal-nav-lock shrink-0" />
                      </div>
                    );
                  }

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
              </div>
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}
