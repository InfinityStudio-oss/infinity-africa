import Link from "next/link";

import { AuthSplitLayout } from "@/components/auth/auth-split-layout";
import { ResendVerificationForm } from "@/components/auth/resend-verification-form";

export const metadata = {
  title: "Resend Verification | InfinityPay",
};

export default function MerchantResendVerificationPage() {
  return (
    <AuthSplitLayout showBrandPanel={false}>
      <h1 className="text-2xl font-bold text-on-surface">Resend your verification link</h1>
      <p className="mt-2 text-sm text-on-surface-variant">
        Signed up but never received the email? Enter the address you registered with and we&apos;ll send a fresh
        link. Use the same address — creating a second account will be refused.
      </p>
      <ResendVerificationForm />
      <p className="mt-6 text-center text-sm text-on-surface-variant">
        Already verified?{" "}
        <Link href="/dashboard/login" className="font-semibold text-primary-container hover:underline">
          Back to login
        </Link>
      </p>
    </AuthSplitLayout>
  );
}
