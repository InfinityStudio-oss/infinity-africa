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

export interface PortalNavGroup {
  /** Null for the items that sit above the first heading. Overview is the
   * only one: giving it a group of its own would be a heading over a
   * single link, which is noise. */
  label: string | null;
  items: PortalNavItem[];
}

/**
 * Twelve flat links in one column meant the sidebar had no shape: Wallet
 * sat next to Collections sat next to Pay by Link, and a merchant looking
 * for "where does my money go out" had to read all twelve and know which
 * of three words we had chosen. The groups below answer that question
 * instead, in the merchant's terms rather than ours.
 *
 * "Money out" is the group this release adds to. Withdrawals and Payouts
 * are genuinely different products - one is approved by a person and
 * spends the Collections balance, the other is an API call against a
 * prefunded wallet - and putting them under one heading is how a merchant
 * comes to understand that they are two ways out of the same account
 * rather than two names for the same thing.
 */
export const PORTAL_NAV_GROUPS: PortalNavGroup[] = [
  {
    label: null,
    items: [{ label: "Overview", href: "/dashboard/overview", icon: "dashboard" }],
  },
  {
    label: "Money in",
    items: [
      { label: "Collections", href: "/portal/collections", icon: "payments" },
      { label: "Pay by Link", href: "/dashboard/pay-by-link", icon: "storefront", requiresVerification: true },
      { label: "Invoices", href: "/dashboard/invoices", icon: "description", requiresVerification: true },
    ],
  },
  {
    label: "Money out",
    items: [
      { label: "Wallet", href: "/portal/wallet", icon: "account_balance" },
      {
        label: "Withdrawals",
        href: "/dashboard/withdrawals",
        icon: "account_balance_wallet",
        requiresVerification: true,
      },
      { label: "Payouts", href: "/portal/payouts", icon: "send_money", requiresVerification: true },
    ],
  },
  {
    label: "Activity",
    items: [
      { label: "Transactions", href: "/portal/transactions", icon: "receipt_long" },
      { label: "Reports", href: "/portal/reports", icon: "bar_chart" },
    ],
  },
  {
    label: "Developer",
    items: [{ label: "API Credentials", href: "/portal/api-credentials", icon: "vpn_key" }],
  },
  {
    label: "Account",
    items: [
      { label: "Team", href: "/dashboard/users", icon: "group_add" },
      { label: "Invite & Earn", href: "/portal/referrals", icon: "card_giftcard", requiresVerification: true },
      { label: "Settings", href: "/dashboard/settings", icon: "settings" },
    ],
  },
];

/**
 * The flat list, still exported.
 *
 * Grouping is a presentation choice; role filtering, the verification
 * guard and the tests that walk every route all want one sequence. Kept
 * derived rather than maintained separately, so a link added to a group
 * cannot go missing from here.
 */
export const PORTAL_NAV_ITEMS: PortalNavItem[] = PORTAL_NAV_GROUPS.flatMap((group) => group.items);
