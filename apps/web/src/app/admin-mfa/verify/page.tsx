import { redirect } from "next/navigation";

import { MfaVerifyForm } from "@/components/admin/mfa-verify-form";
import { SignOutLink } from "@/components/admin/sign-out-link";
import {
  MFA_ENROLL_PATH,
  getSuperAdminMfaState,
} from "@/lib/auth/super-admin-mfa";
import { requireSuperAdminIdentity } from "@/lib/supabase/protected-route";

export default async function AdminMfaVerifyPage() {
  // Admin identity only — see the enrol page for why this is not
  // requireSuperAdmin().
  const { supabase } = await requireSuperAdminIdentity();

  const state = await getSuperAdminMfaState(supabase);
  if (state === "satisfied") redirect("/super-admin");
  if (state === "needs-enrollment") redirect(MFA_ENROLL_PATH);

  return (
    <div>
      <h1 className="text-xl font-bold text-on-surface">Two-factor verification</h1>
      <p className="mt-2 text-sm text-on-surface-variant">
        Open your authenticator app and enter the current code for InfinityPay.
      </p>

      <div className="mt-6">
        <MfaVerifyForm />
      </div>

      <p className="mt-5 text-xs text-on-surface-variant">
        Lost access to your authenticator? Ask the other platform admin to help you recover — see the Super
        Admin MFA runbook.
      </p>

      <div className="mt-6 border-t border-outline-variant pt-4">
        <SignOutLink />
      </div>
    </div>
  );
}
