import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";

export const metadata = {
  title: "Reset Password | InfinityPay",
};

export default function MerchantResetPasswordPage() {
  return (
    <AuthSplitLayout>
      <h1 className="text-2xl font-bold text-on-surface">Set a new password</h1>
      <p className="mt-2 text-sm text-on-surface-variant">Choose a new password for your merchant account.</p>
      <ResetPasswordForm />
    </AuthSplitLayout>
  );
}
