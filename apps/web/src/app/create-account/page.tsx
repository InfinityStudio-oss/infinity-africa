import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
import { CreateAccountForm } from "@/components/auth/create-account-form";

export const metadata = {
  title: "Create your InfinityPay account",
  description: "Create your InfinityPay account and submit your business details for review.",
};

export default function CreateAccountPage() {
  return (
    <AuthSplitLayout maxWidthClassName="max-w-2xl">
      <h1 className="text-2xl font-bold text-on-surface">Create your InfinityPay account</h1>
      <p className="mt-2 text-sm text-on-surface-variant">
        Tell us about you and your business. We&apos;ll verify your email and review your business before activating
        your dashboard.
      </p>
      <CreateAccountForm />
    </AuthSplitLayout>
  );
}
