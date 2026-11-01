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
                  active
                    ? "inline-block px-4 py-2.5 text-sm font-semibold text-primary border-b-2 border-primary -mb-px"
                    : "inline-block px-4 py-2.5 text-sm font-medium text-on-surface-variant border-b-2 border-transparent hover:text-on-background"
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
