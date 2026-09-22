import Link from "next/link";

import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";

export const metadata = {
  title: "Forgot Password | InfinityPay",
};

export default function MerchantForgotPasswordPage() {
  return (
    <AuthSplitLayout>
      <h1 className="text-2xl font-bold text-on-surface">Reset your password</h1>
      <p className="mt-2 text-sm text-on-surface-variant">
        Enter the email address on your merchant account and we&apos;ll send you a link to reset your password.
      </p>
      <ForgotPasswordForm />
      <p className="mt-6 text-center text-sm text-on-surface-variant">
        Remembered it after all?{" "}
        <Link href="/dashboard/login" className="font-semibold text-primary-container hover:underline">
          Back to login
        </Link>
      </p>
    </AuthSplitLayout>
  );
}
