import { adminLogout } from "@/lib/supabase/logout";

/**
 * The way out of the MFA pages.
 *
 * Worth having: an admin who cannot complete the challenge — wrong device,
 * lost phone — would otherwise be stuck on a page with no exit, since the
 * Super Admin console itself is unreachable until verification passes.
 * Reuses the existing adminLogout action so sign-out behaves identically
 * here and in the console topbar.
 */
export function SignOutLink() {
  return (
    <form action={adminLogout}>
      <button
        type="submit"
        className="text-sm font-medium text-on-surface-variant underline hover:text-on-surface"
      >
        Sign out
      </button>
    </form>
  );
}
