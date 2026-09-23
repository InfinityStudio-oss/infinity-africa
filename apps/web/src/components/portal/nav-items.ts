export interface PortalNavItem {
  label: string;
  href: string;
  icon: string;
}

export const PORTAL_NAV_ITEMS: PortalNavItem[] = [
  { label: "Overview", href: "/dashboard/overview", icon: "dashboard" },
  { label: "Wallet", href: "/portal/wallet", icon: "account_balance" },
  { label: "Collections", href: "/portal/collections", icon: "payments" },
  { label: "Pay by Link", href: "/dashboard/pay-by-link", icon: "storefront" },
  { label: "Withdrawals", href: "/dashboard/withdrawals", icon: "account_balance_wallet" },
  { label: "Transactions", href: "/portal/transactions", icon: "receipt_long" },
  { label: "Invoices", href: "/dashboard/invoices", icon: "description" },
  { label: "Team", href: "/dashboard/users", icon: "group_add" },
  { label: "API Credentials", href: "/portal/api-credentials", icon: "vpn_key" },
  { label: "Reports", href: "/portal/reports", icon: "bar_chart" },
  { label: "Settings", href: "/dashboard/settings", icon: "settings" },
];
