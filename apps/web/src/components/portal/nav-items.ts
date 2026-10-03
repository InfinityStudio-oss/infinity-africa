export interface PortalNavItem {
  label: string;
  href: string;
  icon: string;
  /** Pages that call requireVerifiedMerchant() and therefore redirect a
   * merchant whose account is still under review straight back to
   * Overview. Marked here so the sidebar can say so instead of letting
   * them click into a blank flash and a silent bounce. Keep in step with
   * the routes that actually call that guard. */
  requiresVerification?: boolean;
}

export const PORTAL_NAV_ITEMS: PortalNavItem[] = [
  { label: "Overview", href: "/dashboard/overview", icon: "dashboard" },
  { label: "Wallet", href: "/portal/wallet", icon: "account_balance" },
  { label: "Collections", href: "/portal/collections", icon: "payments" },
  { label: "Pay by Link", href: "/dashboard/pay-by-link", icon: "storefront", requiresVerification: true },
  { label: "Withdrawals", href: "/dashboard/withdrawals", icon: "account_balance_wallet", requiresVerification: true },
  { label: "Transactions", href: "/portal/transactions", icon: "receipt_long" },
  { label: "Invoices", href: "/dashboard/invoices", icon: "description", requiresVerification: true },
  { label: "Team", href: "/dashboard/users", icon: "group_add" },
  { label: "API Credentials", href: "/portal/api-credentials", icon: "vpn_key" },
  { label: "Reports", href: "/portal/reports", icon: "bar_chart" },
  { label: "Settings", href: "/dashboard/settings", icon: "settings" },
];
