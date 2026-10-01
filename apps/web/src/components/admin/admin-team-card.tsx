import { Card } from "@/components/portal/card";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatDateTime } from "@/lib/format";
import type { AdminTeamMember } from "@/lib/admin/types";

/**
 * The real platform_admins roster.
 *
 * This card used to render three invented people — "David Komba",
 * "Rehema Ally" and an "Admin User", with Operations and Support tiers
 * that have never existed (platform_admins.role has a CHECK constraint
 * permitting only SUPER_ADMIN). On a live platform that is worse than
 * showing nothing: it answers "who can reach every merchant's money?"
 * with fiction, and answers it confidently.
 *
 * There is deliberately no "invite" action here. Granting super-admin is
 * done by hand, with an audit entry, because an endpoint that creates
 * super admins turns any single admin-session compromise into a
 * permanent platform takeover — see docs/SUPER_ADMIN_MFA_RUNBOOK.md.
 */
export function AdminTeamCard({ team }: { team: AdminTeamMember[] | null }) {
  return (
    <Card id="admins" className="scroll-mt-24">
      <div className="mb-5">
        <h3 className="text-2xl font-semibold text-on-background">Admin Team</h3>
        <p className="mt-1 text-sm text-on-surface-variant">
          Everyone with super-admin access to every merchant on the platform.
        </p>
      </div>

      {team === null ? (
        // Never "no admins": a signed-in super admin is proof of at least
        // one, so an empty roster here always means the read failed.
        <p className="text-sm text-error">
          Couldn&apos;t load the admin roster. This is a failed request, not an empty list — retry shortly, and
          check the API is reachable if it persists.
        </p>
      ) : team.length === 0 ? (
        <p className="text-sm text-on-surface-variant">No platform admins found.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                <th className="px-5 py-3 font-semibold">Admin</th>
                <th className="px-5 py-3 font-semibold">Role</th>
                <th className="px-5 py-3 font-semibold">Last Signed In</th>
                <th className="px-5 py-3 font-semibold">Added</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {team.map((member) => {
                const label = member.full_name || member.email || member.user_id;
                return (
                  <tr key={member.id} className="border-t border-surface-container-highest">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-xs shrink-0">
                          {label.charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <div className="font-medium text-on-background">{label}</div>
                          {member.full_name && member.email && (
                            <div className="text-xs text-on-surface-variant">{member.email}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-on-surface-variant">{member.role}</td>
                    <td className="px-5 py-3.5">
                      {/* An admin who has never signed in is not a working
                          backup. Saying so here is the whole reason this
                          column exists. */}
                      {member.last_sign_in_at ? (
                        <span className="text-on-surface-variant">{formatDateTime(member.last_sign_in_at)}</span>
                      ) : (
                        <StatusBadge label="Never signed in" tone="pending" dot />
                      )}
                    </td>
                    <td className="px-5 py-3.5 text-on-surface-variant">{formatDateTime(member.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-5 text-xs text-on-surface-variant border-t border-surface-container-highest pt-4">
        Super-admin access is granted manually, by direct database change with an audit entry. There is no
        self-service path on purpose: an endpoint that creates super admins would turn one compromised admin
        session into a permanent platform takeover.
      </p>
    </Card>
  );
}
