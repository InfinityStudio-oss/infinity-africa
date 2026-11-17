import { PageHeader } from "@/components/portal/page-header";
import { CollectionPricingRulesView } from "@/components/super-admin/collection-pricing-rules-view";
import { PricingRulesView } from "@/components/super-admin/pricing-rules-view";
import {
  listAdminMerchants,
  listCollectionPricingRulesForMerchant,
  listPlatformFallbackCollectionPricingRules,
  listPlatformFallbackPricingRules,
  listPricingRulesForMerchant,
} from "@/lib/admin/live-api";

export const metadata = {
  title: "Collection Pricing Rules | InfinityPay Super Admin",
};

export default async function SuperAdminPricingRulesPage({
  searchParams,
}: {
  searchParams: Promise<{ merchant_id?: string }>;
}) {
  const { merchant_id: selectedMerchantId } = await searchParams;

  const [merchants, collectionPlatformRules, collectionMerchantRules, withdrawalPlatformRules, withdrawalMerchantRules] =
    await Promise.all([
      listAdminMerchants(),
      listPlatformFallbackCollectionPricingRules(),
      selectedMerchantId ? listCollectionPricingRulesForMerchant(selectedMerchantId) : Promise.resolve([]),
      listPlatformFallbackPricingRules(),
      selectedMerchantId ? listPricingRulesForMerchant(selectedMerchantId) : Promise.resolve([]),
    ]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Collection Pricing Rules"
        description="Configure flexible, per-business collection fees — the exact rate is negotiated separately with each business/customer."
      />
      <CollectionPricingRulesView
        merchants={merchants}
        platformRules={collectionPlatformRules}
        selectedMerchantId={selectedMerchantId ?? null}
        merchantRules={collectionMerchantRules}
      />

      {/* Same fault as the note above, found while fixing it: this sits on
          the gradient with no background at all, and the summary is the
          only thing visible while collapsed. `text-on-surface-variant`
          put it at 1.05-1.76:1 on navy. `on-gradient-muted` is 4.94-9.12:1
          and still reads as secondary, which is what an inactive section
          wants. */}
      <details className="rounded-lg border border-surface-container-highest">
        <summary className="cursor-pointer px-5 py-4 text-sm font-semibold on-gradient-muted">
          Withdrawal Pricing Rules (Inactive) — no longer charges any merchant
        </summary>
        <div className="p-5 pt-0 space-y-8">
          <PricingRulesView
            merchants={merchants}
            platformRules={withdrawalPlatformRules}
            selectedMerchantId={selectedMerchantId ?? null}
            merchantRules={withdrawalMerchantRules}
          />
        </div>
      </details>
    </div>
  );
}
