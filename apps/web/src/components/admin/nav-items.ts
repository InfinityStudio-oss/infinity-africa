export interface AdminNavItem {
  label: string;
  href: string;
  icon: string;
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
  { label: "Document Requests", href: "/super-admin/document-requests", icon: "folder_shared" },
  { label: "Disputes", href: "/super-admin/disputes", icon: "gavel" },
  { label: "Pricing Rules", href: "/super-admin/pricing-rules", icon: "sell" },
  { label: "API Keys", href: "/super-admin/api-keys", icon: "api" },
  { label: "Webhooks & Reconciliation", href: "/super-admin/webhooks", icon: "webhook" },
  { label: "Audit Logs", href: "/super-admin/audit-logs", icon: "history" },
  { label: "Inquiries", href: "/super-admin/inquiries", icon: "mail" },
  { label: "Settings", href: "/admin/settings", icon: "settings" },
];
