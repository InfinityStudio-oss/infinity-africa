import Link from "next/link";

import { LoginForm } from "@/components/auth/login-form";

export const metadata = {
  title: "Super Admin Login | InfinityPay",
};

/** Same centred-card layout as the merchant login at /dashboard/login —
 * the two sign-in screens should not look like different products. The
 * heading still says Super Admin so nobody mistakes one for the other. */
export default function AdminLoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-container-low px-4 py-10 sm:px-6 sm:py-12">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 flex items-center justify-center">
          <span className="text-2xl font-bold tracking-tight text-primary">InfinityPay</span>
        </Link>

        <div className="rounded-2xl border border-outline-variant bg-surface p-7 shadow-sm sm:p-9">
          <h1 className="text-xl font-bold text-on-surface sm:text-2xl">Super Admin Login</h1>
          <p className="mt-1 text-sm text-on-surface-variant">Sign in to the InfinityPay platform admin console.</p>
          <LoginForm variant="admin" />
        </div>
      </div>
    </main>
  );
}
