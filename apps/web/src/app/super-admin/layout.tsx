import { requireSuperAdmin } from "@/lib/supabase/protected-route";
import { AdminShell } from "@/components/admin/admin-shell";
import { listAdminNotifications } from "@/lib/admin/live-api";
import { uiPreviewEnabled } from "@/lib/auth/ui-preview";

export const metadata = {
  title: "Super Admin | InfinityPay",
  robots: { index: false, follow: false },
};

export default async function SuperAdminLayout({ children }: { children: React.ReactNode }) {
  const user = uiPreviewEnabled() ? null : await requireSuperAdmin();
  const notifications = await listAdminNotifications();
  const meta = (user?.user_metadata ?? {}) as Record<string, unknown>;
  return (
    <AdminShell
      notificationCount={notifications.filter((n) => !n.is_read).length}
      adminEmail={user?.email ?? ""}
      adminFullName={typeof meta.full_name === "string" ? meta.full_name : null}
    >
      {children}
    </AdminShell>
  );
}
