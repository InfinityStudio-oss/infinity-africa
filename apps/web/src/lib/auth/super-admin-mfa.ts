import "server-only";

// Deliberately imports nothing from lib/supabase/protected-route: that
// module imports THIS one, and a cycle between them leaves one side
// undefined at runtime. requireSuperAdminIdentity therefore lives over
// there, next to requireUser, rather than here.

export const MFA_ENROLL_PATH = "/admin-mfa/enroll";
export const MFA_VERIFY_PATH = "/admin-mfa/verify";

/**
 * Whether platform admins must present a second factor.
 *
 * Read server-side only, never `NEXT_PUBLIC_` — this is a security posture,
 * not something the browser needs. It must match REQUIRE_SUPER_ADMIN_MFA on
 * the API service: the backend is the authority (it refuses any /v1/admin
 * call from an aal1 session), and this flag only decides whether the portal
 * routes an admin to the MFA pages first. If the two ever disagree in the
 * unsafe direction the portal renders and every API call then fails with
 * `mfa_required` — confusing, but it fails closed, which is the right way
 * round for a mismatch.
 */
export function superAdminMfaRequired(): boolean {
  return process.env.REQUIRE_SUPER_ADMIN_MFA === "true";
}

type MfaState = "satisfied" | "needs-enrollment" | "needs-verification";

/** Just the two MFA calls this needs — structural, so it accepts the real
 * Supabase server client without importing the module that creates it. */
type SupabaseLike = {
  auth: {
    mfa: {
      getAuthenticatorAssuranceLevel: () => Promise<{ data: { currentLevel?: string | null } | null }>;
      listFactors: () => Promise<{ data: { totp?: Array<{ id: string; status: string }> } | null }>;
    };
  };
};

/**
 * Where this session stands, asked of Supabase rather than inferred.
 *
 * `currentLevel` reflects what the session actually presented, so it is the
 * thing to branch on — not "does a factor exist", which only says whether
 * enrolment has happened, never whether it was used this session.
 *
 * Any failure resolves to needs-verification rather than satisfied: if we
 * cannot establish that a second factor was presented, the answer is no.
 */
export async function getSuperAdminMfaState(supabase: SupabaseLike): Promise<MfaState> {
  try {
    const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    if (aal?.currentLevel === "aal2") return "satisfied";

    const { data: factors } = await supabase.auth.mfa.listFactors();
    const verified = (factors?.totp ?? []).filter((factor) => factor.status === "verified");
    return verified.length > 0 ? "needs-verification" : "needs-enrollment";
  } catch {
    return "needs-verification";
  }
}
