/** Platform + merchant-scoped user roles. Mirrors platform_admins/merchant_users in the DB schema. */
export enum UserRole {
  SUPER_ADMIN = "SUPER_ADMIN",
  MERCHANT_ADMIN = "MERCHANT_ADMIN",
  MERCHANT_STAFF = "MERCHANT_STAFF",
  DEVELOPER = "DEVELOPER",
}

export const USER_ROLE_LABELS: Record<UserRole, string> = {
  [UserRole.SUPER_ADMIN]: "Super Admin",
  [UserRole.MERCHANT_ADMIN]: "Admin",
  [UserRole.MERCHANT_STAFF]: "Staff",
  [UserRole.DEVELOPER]: "Developer",
};

/**
 * Roles a user can hold *within* a specific merchant (merchant_users.role).
 * Excludes SUPER_ADMIN, which is platform-wide and lives in platform_admins,
 * not merchant_users.
 */
export const MERCHANT_ROLES = [
  UserRole.MERCHANT_ADMIN,
  UserRole.MERCHANT_STAFF,
  UserRole.DEVELOPER,
] as const;
