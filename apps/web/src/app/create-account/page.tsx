import { CreateAccountForm } from "@/components/auth/create-account-form";
import { Footer } from "@/components/site/footer";
import { Header } from "@/components/site/header";

export const metadata = {
  title: "Create your InfinityPay account",
  description: "Create your InfinityPay account and submit your business details for review.",
};

/** Signup is a public marketing-funnel page, not a bare auth screen — it
 * carries the site header/footer so someone can still reach Solutions,
 * Documentation or Contact mid-form instead of hitting a dead end, and a
 * centred single column rather than the split layout the shorter auth
 * pages use, because this form is long enough to need the full width. */
export default function CreateAccountPage() {
  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-14 sm:px-6 sm:py-16 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-widest text-primary-container">Get Started</p>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-on-surface sm:text-4xl">
          Create your InfinityPay account
        </h1>
        <p className="mt-4 max-w-xl text-base leading-relaxed text-on-surface-variant">
          Tell us about you and your business. We&apos;ll verify your email and review your business before
          activating your dashboard.
        </p>
        <CreateAccountForm />
      </main>
      <Footer />
    </>
  );
}
