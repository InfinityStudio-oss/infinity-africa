import { PageHeader } from "@/components/portal/page-header";
import { AdminSettingsPanels } from "@/components/admin/admin-settings-panels";
import { AdminTeamCard } from "@/components/admin/admin-team-card";
import { listAdminTeam } from "@/lib/admin/live-api";

export const metadata = {
  title: "Settings | InfinityPay Super Admin",
};

const TABS = [
  { label: "Platform", href: "#platform" },
  { label: "Security", href: "#security" },
  { label: "Notifications", href: "#notifications" },
  { label: "Admin Team", href: "#admins" },
];

/** Server-rendered so the Admin Team card can read the real
 * platform_admins roster: lib/admin/live-api.ts is "server-only", and the
 * roster has to come from somewhere other than the invented list this
 * page used to show. */
export default async function AdminSettingsPage() {
  const team = await listAdminTeam();

  return (
    <div className="space-y-8">
      <PageHeader title="Settings" description="Platform-wide configuration and admin team management." />

      <div className="flex flex-wrap gap-2">
        {TABS.map((tab, index) => (
          <a
            key={tab.href}
            href={tab.href}
            className={
              index === 0
                ? "px-4 py-2 rounded-full bg-primary-container text-on-primary text-sm font-semibold"
                : "px-4 py-2 rounded-full bg-surface-container-low text-on-surface-variant text-sm font-semibold hover:bg-surface-container-highest transition-colors"
            }
          >
            {tab.label}
          </a>
        ))}
      </div>

      <AdminSettingsPanels />

      <AdminTeamCard team={team} />
    </div>
  );
}
