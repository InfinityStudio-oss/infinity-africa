import { requireCurrentUser } from "@/lib/auth/current-user";
import { requireVerifiedMerchant } from "@/lib/onboarding/guard";
import { PaymentLinksView } from "@/components/merchant/payment-links-view";
import { PortalShell } from "@/components/portal/portal-shell";

export const metadata = {
  title: "Payment Links | InfinityPay",
};

export default async function PaymentLinksPage() {
  await requireCurrentUser("/merchant/login");
  await requireVerifiedMerchant();

  return (
    <PortalShell>
      <PaymentLinksView />
    </PortalShell>
  );
}
