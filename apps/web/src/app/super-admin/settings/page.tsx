import { requireSuperAdmin } from "@/lib/supabase/protected-route";
import { PageHeader } from "@/components/portal/page-header";
import { UpdatePasswordForm } from "@/components/auth/update-password-form";

export const metadata = {
  title: "Settings | InfinityPay Admin",
};

export default async function SuperAdminSettingsPage() {
  const user = await requireSuperAdmin();

  return (
    <div className="space-y-8">
      <PageHeader title="Settings" description="Manage your account security." />
      {/* requireSuperAdmin() only ever succeeds against a real Supabase
          session (see lib/supabase/protected-route.ts) — the mock-auth
          fallback is structurally unreachable here, so source is always
          "supabase" for a signed-in Super Admin. */}
      <UpdatePasswordForm email={user.email ?? ""} source="supabase" />
    </div>
  );
}
