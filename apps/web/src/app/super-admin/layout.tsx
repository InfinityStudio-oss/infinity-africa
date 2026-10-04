import { requireSuperAdmin } from "@/lib/supabase/protected-route";
import { AdminShell } from "@/components/admin/admin-shell";
import { listAdminNotifications } from "@/lib/admin/live-api";
import { uiPreviewEnabled } from "@/lib/auth/ui-preview";

export const metadata = {
  title: "Super Admin | InfinityPay",
  robots: { index: false, follow: false },
};

export default async function SuperAdminLayout({ children }: { children: React.ReactNode }) {
  // Started together, not one after the other. Proving who the admin is
  // and counting their unread notifications are independent round trips —
  // one to Supabase, one to the API — and awaiting them in sequence put
  // the slower of the two on top of the faster on every page load.
  //
  // Safe to start the notification fetch before the identity check
  // resolves: that endpoint is require_super_admin-gated on the backend,
  // so a caller who turns out not to be an admin gets a 401 and an empty
  // list, and requireSuperAdmin's redirect still wins. Nothing is rendered
  // from a request that was not authorised.
  const [user, notifications] = await Promise.all([
    uiPreviewEnabled() ? Promise.resolve(null) : requireSuperAdmin(),
    listAdminNotifications(),
  ]);
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
