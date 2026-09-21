import Link from "next/link";

import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";

export const metadata = {
  title: "Forgot Password | InfinityPay Admin",
};

export default function AdminForgotPasswordPage() {
  return (
    <AuthSplitLayout>
      <h1 className="text-2xl font-bold text-on-surface">Reset your password</h1>
      <p className="mt-2 text-sm text-on-surface-variant">
        Enter the email address on your Super Admin account and we&apos;ll send you a link to reset your password.
      </p>
      <ForgotPasswordForm resetPasswordPath="/admin-login/reset-password" />
      <p className="mt-6 text-center text-sm text-on-surface-variant">
        Remembered it after all?{" "}
        <Link href="/admin-login" className="font-semibold text-primary-container hover:underline">
          Back to login
        </Link>
      </p>
    </AuthSplitLayout>
  );
}
