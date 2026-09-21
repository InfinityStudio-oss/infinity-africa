import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
import { CreateAccountForm } from "@/components/auth/create-account-form";

export const metadata = {
  title: "Create Account | InfinityPay",
  description: "Create your InfinityPay merchant account and submit your business details for review.",
};

export default function CreateAccountPage() {
  return (
    <AuthSplitLayout maxWidthClassName="max-w-2xl">
      <h1 className="text-2xl font-bold text-on-surface">Create your merchant account</h1>
      <p className="mt-2 text-sm text-on-surface-variant">
        Fill in your account and business details below. When you submit, InfinityPay reviews your application — you
        can sign in and start collecting payments once your account is approved.
      </p>
      <CreateAccountForm />
    </AuthSplitLayout>
  );
}
