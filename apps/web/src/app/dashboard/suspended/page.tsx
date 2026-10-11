import Link from "next/link";

import { LogOutButton } from "@/components/auth/log-out-button";
import { merchantLogout } from "@/lib/supabase/logout";

export const metadata = {
  title: "Account suspended | InfinityPay",
  robots: { index: false, follow: false },
};

/**
 * Where a suspended or closed business lands.
 *
 * Login refuses a suspended merchant outright (lib/auth/actions.ts), so
 * this page exists for the session that was already open when the Super
 * Admin suspended the account: the portal layout sends it here instead of
 * letting every panel on the dashboard fail with a 403 and no explanation.
 *
 * No merchant data is loaded or shown here — the account is shut off, and
 * the page only needs to say so and offer the way out.
 */
export default function AccountSuspendedPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-container-low px-4 py-10 sm:px-6">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 flex items-center justify-center">
          <span className="text-2xl font-bold tracking-tight text-primary">InfinityPay</span>
        </Link>

        <div className="rounded-2xl border border-outline-variant bg-surface p-7 text-center shadow-sm sm:p-9">
          <h1 className="text-xl font-bold text-on-surface sm:text-2xl">This account is suspended</h1>
          <p className="mt-3 text-sm text-on-surface-variant">
            Your InfinityPay business account has been suspended, so collections, payment links,
            invoices, API keys and withdrawals are all switched off.
          </p>
          <p className="mt-3 text-sm text-on-surface-variant">
            If you believe this is a mistake, contact InfinityPay support and we will review it.
          </p>

          <form action={merchantLogout} className="mt-7">
            <LogOutButton className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-on-primary transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60" />
          </form>
        </div>
      </div>
    </main>
  );
}
