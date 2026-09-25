import { redirect } from "next/navigation";

import { MfaEnrollForm } from "@/components/admin/mfa-enroll-form";
import { SignOutLink } from "@/components/admin/sign-out-link";
import {
  MFA_VERIFY_PATH,
  getSuperAdminMfaState,
  requireSuperAdminIdentity,
  superAdminMfaRequired,
} from "@/lib/auth/super-admin-mfa";

export default async function AdminMfaEnrollPage() {
  // Admin identity only — not requireSuperAdmin(), which would redirect
  // back here and loop. A merchant or a signed-out visitor is still turned
  // away by the platform_admins lookup inside this.
  const { supabase } = await requireSuperAdminIdentity();

  // Someone who has already enrolled belongs on the challenge page, and
  // someone already verified has no business here at all.
  const state = await getSuperAdminMfaState(supabase);
  if (state === "satisfied") redirect("/super-admin");
  if (state === "needs-verification") redirect(MFA_VERIFY_PATH);

  return (
    <div>
      <h1 className="text-xl font-bold text-on-surface">Set up two-factor authentication</h1>
      <p className="mt-2 text-sm text-on-surface-variant">
        Platform admin accounts approve withdrawals and change pricing, so they need a second factor. Scan this
        code with an authenticator app such as Google Authenticator, 1Password or Authy.
      </p>

      {!superAdminMfaRequired() && (
        <p className="mt-4 rounded-lg bg-surface-variant/40 px-3 py-2 text-xs text-on-surface-variant">
          Two-factor authentication isn&apos;t enforced yet. You can set it up now so it&apos;s ready before it
          is switched on.
        </p>
      )}

      <div className="mt-6">
        <MfaEnrollForm />
      </div>

      <div className="mt-6 border-t border-outline-variant pt-4">
        <SignOutLink />
      </div>
    </div>
  );
}
