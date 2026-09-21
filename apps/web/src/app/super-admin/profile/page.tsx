import { requireSuperAdmin } from "@/lib/supabase/protected-route";
import { PageHeader } from "@/components/portal/page-header";
import { ProfileView } from "@/components/super-admin/profile-view";

export const metadata = {
  title: "Profile | InfinityPay Admin",
};

export default async function SuperAdminProfilePage() {
  const user = await requireSuperAdmin();
  const meta = (user.user_metadata ?? {}) as Record<string, unknown>;
  const fullName = typeof meta.full_name === "string" ? meta.full_name : "";

  return (
    <div className="space-y-8">
      <PageHeader title="Profile" description="Your Super Admin account details." />
      <ProfileView email={user.email ?? ""} fullName={fullName} />
    </div>
  );
}
