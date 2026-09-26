"use client";

import { useFormStatus } from "react-dom";

import { adminLogout } from "@/lib/supabase/logout";

/**
 * Signing out revokes the Supabase session globally, not just locally, so
 * it waits on a network round trip before the redirect. That is the right
 * trade for an admin account — a session that stayed valid server-side
 * after "sign out" would be worse than a slow button — but without any
 * feedback the wait reads as a broken click, and people click again.
 */
function SignOutButton() {
  const { pending } = useFormStatus();

  return (
    <button
      type="submit"
      disabled={pending}
      className="text-sm font-medium text-on-surface-variant underline hover:text-on-surface disabled:cursor-not-allowed disabled:no-underline disabled:opacity-60"
    >
      {pending ? "Signing out…" : "Sign out"}
    </button>
  );
}

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
      <SignOutButton />
    </form>
  );
}
