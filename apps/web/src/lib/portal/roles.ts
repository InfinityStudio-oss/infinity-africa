import { MERCHANT_ROLES, UserRole, USER_ROLE_LABELS } from "@infinity/shared";

export { MERCHANT_ROLES, UserRole, USER_ROLE_LABELS };

/**
 * Per-role portal page access, keyed by nav href. "Overview" is intentionally
 * included for every role even though it isn't listed per-role in the product
 * spec, since it's the landing page every merchant user hits after auth.
 * DEVELOPER's "integration settings" access maps to the existing Settings
 * page, since there is no separate integration-settings subsection.
 */
export const ROLE_ALLOWED_PATHS: Record<UserRole, string[] | "*"> = {
  [UserRole.SUPER_ADMIN]: "*",
  [UserRole.MERCHANT_ADMIN]: "*",
  [UserRole.MERCHANT_STAFF]: [
    "/dashboard/overview",
    "/portal",
    "/portal/collections",
    "/dashboard/invoices",
    "/portal/transactions",
    "/portal/support",
    "/dashboard/profile",
    "/dashboard/settings",
  ],
  [UserRole.DEVELOPER]: [
    "/dashboard/overview",
    "/portal",
    "/portal/api-credentials",
    "/dashboard/profile",
    "/dashboard/settings",
  ],
};

export function isPathAllowedForRole(role: UserRole, pathname: string): boolean {
  const allowed = ROLE_ALLOWED_PATHS[role];
  if (allowed === "*") return true;
  return allowed.some((href) =>
    href === "/portal" || href === "/dashboard/overview" ? pathname === href : pathname.startsWith(href),
  );
}
