import { requireCurrentUser } from "@/lib/auth/current-user";
import { requireVerifiedMerchant } from "@/lib/onboarding/guard";
import { InvoicesView } from "@/components/merchant/invoices-view";
import { PortalShell } from "@/components/portal/portal-shell";

export const metadata = {
  title: "Invoices | InfinityPay",
};

export default async function InvoicesPage() {
  await requireCurrentUser("/dashboard/login");
  await requireVerifiedMerchant();

  return (
    <PortalShell>
      <InvoicesView />
    </PortalShell>
  );
}
