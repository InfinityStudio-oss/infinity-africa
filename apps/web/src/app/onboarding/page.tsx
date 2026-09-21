import { redirect } from "next/navigation";

import { requireCurrentUser } from "@/lib/auth/current-user";
import { getOnboardingStatus } from "@/lib/onboarding/api";
import { OnboardingForm } from "@/components/onboarding/onboarding-form";
import { Header } from "@/components/site/header";
import { Footer } from "@/components/site/footer";

export const metadata = {
  title: "Merchant Onboarding | InfinityPay",
};

export default async function OnboardingPage() {
  const user = await requireCurrentUser("/merchant/login");

  const onboarding = await getOnboardingStatus();
  if (onboarding?.next_path === "/merchant/overview") {
    redirect("/merchant/overview");
  }

  return (
    <div className="bg-surface text-on-surface antialiased flex-1 flex flex-col">
      <Header />
      <main className="flex-1 py-16 px-4 md:px-10 bg-surface-container-lowest">
        <div className="max-w-[720px] mx-auto">
          <span className="text-xs font-semibold text-primary-container uppercase tracking-wide">
            Merchant Onboarding
          </span>
          <h1 className="text-2xl md:text-4xl font-bold mt-2 mb-3 text-on-surface tracking-tight">
            Tell us about your business
          </h1>
          <p className="text-sm text-on-surface-variant mb-10">
            Complete your business details to submit your account for verification.
          </p>
          <OnboardingForm accountStatus={onboarding?.account_status ?? null} defaultPhone={user.phone} />
        </div>
      </main>
      <Footer />
    </div>
  );
}
