import Link from "next/link";

import { LoginForm } from "@/components/auth/login-form";

export const metadata = {
  title: "Log in | InfinityPay",
};

export default async function MerchantLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ notice?: string }>;
}) {
  // `notice` is only ever set by our own redirects (the email-verification
  // callback in app/auth/callback/route.ts), never user-controlled free
  // text worth sanitising further — React escapes it on render anyway.
  const { notice } = await searchParams;

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-container-low px-4 py-10 sm:px-6 sm:py-12">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 flex items-center justify-center">
          <span className="text-2xl font-bold tracking-tight text-primary">InfinityPay</span>
        </Link>

        <div className="rounded-2xl border border-outline-variant bg-surface p-7 shadow-sm sm:p-9">
          <h1 className="text-xl font-bold text-on-surface sm:text-2xl">Log in</h1>
          <p className="mt-1 text-sm text-on-surface-variant">Sign in to manage your InfinityPay account.</p>
          {notice && (
            <div className="mt-6 rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">{notice}</div>
          )}
          <LoginForm variant="merchant" />
        </div>
      </div>
    </main>
  );
}
