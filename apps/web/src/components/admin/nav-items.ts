export interface AdminNavItem {
  label: string;
  href: string;
  icon: string;
  /** Nested entries, rendered indented under the parent. The parent is
   * still a link — there is no "group header that goes nowhere" here, so
   * clicking Notifications lands somewhere useful rather than doing
   * nothing, and the children are shortcuts to the two tabs. */
  children?: AdminNavItem[];
}

// The following once linked here but were removed 2026-08-25: Customers,
// Reconciliation Center, Settlement Accounts, Compliance/KYC, Provider
// Status, Support Tickets — all backed by /admin/* pages that are entirely
// hardcoded mock data (see lib/admin/api.ts's own docstring), never wired to
// a real backend. Rather than show fabricated numbers (e.g. a "1,158
// Verified Merchants" count on a platform with 2 real merchants), they're
// unlinked until each one has a real implementation behind it. Four have
// one now: API Keys and Customers got their own real pages; Compliance/KYC
// and Reconciliation Center turned out to be the same real underlying data
// as two already-real pages (Onboarding Requests, Webhooks) — rather than
// build a second page over the same table, those two got real KPIs/columns
// added and were relabeled ("Onboarding & Compliance/KYC",
// "Webhooks & Reconciliation") instead of gaining new nav entries.
// Customers itself is derived, not read from a table — public.customers
// exists in the schema but nothing ever writes to it (see
// app/services/admin_customers.py's docstring); the real page groups
// actual collections by merchant + customer phone instead. Settlement
// Accounts, Provider Status, and Support Tickets still have no real data
// model behind them. The old /admin/* mock page files still exist, just no
// longer reachable from here.
//
// Unlinked 2026-10-09 at the platform owner's request: Document Requests,
// Disputes, Inquiries. Unlike the 2026-08-25 removals above these are all
// real, working pages over real tables — they are hidden because the
// business is not running those workflows, not because they are unfinished.
//
// Their routes, APIs and tables are untouched, so each is one line away
// from coming back. Two things still write to them and are worth knowing
// about:
//   - POST /v1/public/inquiries, from the public /contact form, which is
//     linked from the marketing site. Inquiries will keep arriving with no
//     page showing them.
//   - POST /v1/public/disputes/report and the merchant-facing dispute and
//     document-submission endpoints, which remain callable.
// If those workflows are genuinely retired, the public forms should go too
// rather than accepting submissions nobody reads.
export const ADMIN_NAV_ITEMS: AdminNavItem[] = [
  { label: "Dashboard", href: "/super-admin", icon: "dashboard" },
  { label: "Businesses", href: "/super-admin/merchants", icon: "storefront" },
  { label: "Business Users", href: "/super-admin/merchant-users", icon: "manage_accounts" },
  { label: "Onboarding & Compliance/KYC", href: "/super-admin/onboarding", icon: "assignment_ind" },
  { label: "Collections", href: "/super-admin/collections", icon: "payments" },
  { label: "Pay by Link", href: "/super-admin/pay-by-link", icon: "storefront" },
  { label: "Invoices", href: "/super-admin/invoices", icon: "receipt" },
  { label: "Customers", href: "/super-admin/customers", icon: "group" },
  { label: "Withdrawals", href: "/super-admin/withdrawals", icon: "receipt_long" },
  { label: "Transactions", href: "/super-admin/transactions", icon: "list_alt" },
  { label: "Risk Monitoring", href: "/super-admin/risk-monitoring", icon: "gpp_maybe" },
  { label: "Pricing Rules", href: "/super-admin/pricing-rules", icon: "sell" },
  { label: "Referrals", href: "/super-admin/referrals", icon: "group_add" },
  { label: "API Keys", href: "/super-admin/api-keys", icon: "api" },
  { label: "Webhooks & Reconciliation", href: "/super-admin/webhooks", icon: "webhook" },
  {
    // Was a standalone "SMS" entry until 2026-11-01. Email notification
    // settings became a Super Admin control at the same time, and two
    // sibling top-level entries for the same job read as two unrelated
    // features — so both now live under one parent, each as a tab.
    //
    // /super-admin/sms still works and redirects, because it is in
    // browser histories and bookmarks and nothing is gained by breaking
    // them.
    label: "Notifications",
    href: "/super-admin/notifications",
    icon: "notifications",
    children: [
      { label: "SMS", href: "/super-admin/notifications/sms", icon: "sms" },
      { label: "Email", href: "/super-admin/notifications/email", icon: "mail" },
    ],
  },
  { label: "Audit Logs", href: "/super-admin/audit-logs", icon: "history" },
  { label: "Settings", href: "/admin/settings", icon: "settings" },
];
