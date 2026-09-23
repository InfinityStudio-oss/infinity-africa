import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
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
    <AuthSplitLayout>
      <h1 className="text-2xl font-bold text-on-surface">Log in</h1>
      <p className="mt-2 text-sm text-on-surface-variant">Sign in to manage your InfinityPay account.</p>
      {notice && (
        <div className="mt-6 rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">{notice}</div>
      )}
      <LoginForm variant="merchant" />
    </AuthSplitLayout>
  );
}
