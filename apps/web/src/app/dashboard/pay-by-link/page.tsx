import { requireCurrentUser } from "@/lib/auth/current-user";
import { requireVerifiedMerchant } from "@/lib/onboarding/guard";
import { PayByLinkView } from "@/components/merchant/pay-by-link-view";
import { PortalShell } from "@/components/portal/portal-shell";

export const metadata = {
  title: "Pay by Link | InfinityPay",
};

export default async function PayByLinkPage() {
  await requireCurrentUser("/dashboard/login");
  await requireVerifiedMerchant();

  return (
    <PortalShell>
      <PayByLinkView />
    </PortalShell>
  );
}
