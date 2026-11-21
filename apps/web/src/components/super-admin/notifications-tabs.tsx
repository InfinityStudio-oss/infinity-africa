"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** The two halves of Notifications.
 *
 * A real link each, not a client-side toggle: each tab is its own route,
 * so the back button works, a tab can be bookmarked, and the SMS page
 * keeps loading its own data on the server exactly as it did when it
 * lived at /super-admin/sms.
 */
const TABS = [
  { href: "/super-admin/notifications/sms", label: "SMS" },
  { href: "/super-admin/notifications/email", label: "Email" },
];

export function NotificationsTabs() {
  const pathname = usePathname();

  return (
    <nav aria-label="Notification channels" className="border-b border-surface-container-highest">
      <ul className="flex gap-1">
        {TABS.map((tab) => {
          const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={
                  // Gradient ink. This row sits straight on the page, not
                  // inside a Card, so the card tokens it used to wear were
                  // measured at 1.56:1 for the active tab and 2.72:1 for
                  // the rest - the selected tab was the LEAST readable
                  // thing on the page, which is the opposite of its job.
                  // White is 17.98:1 here and 9.05:1 over the glow.
                  active
                    ? "inline-block px-4 py-2.5 text-sm font-semibold text-white border-b-2 border-[#22b8cf] -mb-px"
                    : "inline-block px-4 py-2.5 text-sm font-medium text-[#cfe6f0] border-b-2 border-transparent hover:text-white"
                }
              >
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
