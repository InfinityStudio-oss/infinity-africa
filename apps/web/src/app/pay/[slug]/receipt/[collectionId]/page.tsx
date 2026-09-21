import { ReceiptCard } from "@/components/payment-link/receipt-card";
import { StatusCard } from "@/components/payment-link/status-card";
import { fetchPublicCollectionReceipt } from "@/lib/payment-links";

export const metadata = {
  title: "Receipt | InfinityPay",
};

export default async function PaymentReceiptPage({
  params,
}: {
  params: Promise<{ slug: string; collectionId: string }>;
}) {
  const { slug, collectionId } = await params;
  const receipt = await fetchPublicCollectionReceipt(slug, collectionId);

  return (
    <div className="flex flex-1 flex-col items-center bg-surface-container px-4 py-6 sm:py-16 print:bg-surface print:py-0">
      <div className="w-full max-w-xl">
        {receipt ? (
          <ReceiptCard receipt={receipt} slug={slug} />
        ) : (
          <div className="overflow-hidden rounded-lg border border-outline-variant bg-surface shadow-sm">
            <StatusCard
              variant="unavailable"
              title="Receipt not available"
              message="This payment hasn't been confirmed yet, or this receipt link is invalid. If you just paid, check the payment page again in a moment."
            />
          </div>
        )}
      </div>
    </div>
  );
}
