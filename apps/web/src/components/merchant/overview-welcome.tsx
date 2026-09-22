import Link from "next/link";

import { Card } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { PageHeader } from "@/components/portal/page-header";
import { StatusBadge } from "@/components/portal/status-badge";
import { ACCOUNT_STATUS_LABELS, AccountStatus } from "@infinity/shared";

const CHECKLIST_ITEMS: { label: string; href?: string; icon: string }[] = [
  { label: "Create your first Pay by Link", href: "/dashboard/pay-by-link", icon: "storefront" },
  { label: "Create your first invoice", href: "/dashboard/invoices", icon: "description" },
  { label: "Generate an API key", href: "/portal/api-credentials?tab=keys", icon: "vpn_key" },
  { label: "Read the API docs", href: "/portal/api-credentials?tab=docs", icon: "menu_book" },
  { label: "Wait for account verification", icon: "verified_user" },
];

export function OverviewWelcome({ accountStatus }: { accountStatus: AccountStatus }) {
  const isPending = accountStatus === AccountStatus.PENDING_VERIFICATION;
  const tone =
    accountStatus === AccountStatus.VERIFIED ? "positive" : accountStatus === AccountStatus.REJECTED ? "negative" : "pending";

  return (
    <div className="space-y-8">
      <PageHeader title="Welcome to InfinityPay" description={`Account status: ${ACCOUNT_STATUS_LABELS[accountStatus]}`} />

      <Card>
        <div className="flex items-start gap-4">
          <StatusBadge label={ACCOUNT_STATUS_LABELS[accountStatus]} tone={tone} dot />
        </div>
        <p className="mt-4 text-sm text-on-surface-variant leading-relaxed">
          {isPending
            ? "Your merchant account is under review. You can start preparing payment links, invoices, and API integration while verification is pending."
            : "Your account status has been updated. Visit onboarding for more details."}
        </p>
      </Card>

      <Card>
        <h3 className="text-lg font-semibold text-on-surface mb-4">Setup Checklist</h3>
        <ul className="space-y-1">
          {CHECKLIST_ITEMS.map((item) =>
            item.href ? (
              <li key={item.label}>
                <Link
                  href={item.href}
                  className="flex items-center gap-3 rounded-lg px-3 py-3 text-sm text-on-surface hover:bg-surface-container transition-colors"
                >
                  <Icon name={item.icon} className="text-[20px] text-primary-container" />
                  {item.label}
                  <Icon name="arrow_forward" className="ml-auto text-[16px] text-outline" />
                </Link>
              </li>
            ) : (
              <li key={item.label} className="flex items-center gap-3 px-3 py-3 text-sm text-on-surface-variant">
                <Icon name={item.icon} className="text-[20px] text-outline" />
                {item.label}
              </li>
            ),
          )}
        </ul>
      </Card>
    </div>
  );
}
