import { PayByLinkForm } from "@/components/payment-link/pay-by-link-form";
import { PaymentForm } from "@/components/payment-link/payment-form";
import { StatusCard } from "@/components/payment-link/status-card";
import { fetchPublicPayByLink } from "@/lib/pay-by-link";
import { fetchPublicPaymentLink, type PaymentLinkStatus, type PublicPaymentLink } from "@/lib/payment-links";

export const metadata = {
  title: "Pay | InfinityPay",
};

const NON_ACTIVE_COPY: Record<Exclude<PaymentLinkStatus, "ACTIVE">, { title: string; message: string }> = {
  EXPIRED: {
    title: "This link has expired",
    message: "This payment link is no longer valid. Ask the merchant to send you a new one.",
  },
  CANCELLED: {
    title: "This link was cancelled",
    message: "The merchant cancelled this payment link. Ask them to send you a new one.",
  },
  PAID: {
    title: "Already paid",
    message: "This payment link has already been paid. No further action is needed.",
  },
};

export default async function CustomerPaymentPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;

  // Resolver rule (feature brief, Pay by Link Part 2): an existing
  // generated/shareable payment link's slug always wins first — a
  // merchant's permanent Pay by Link page is only ever checked as a
  // fallback, so no existing shared /pay/{slug} link can ever be
  // shadowed by a later-created permanent page.
  const link = await fetchPublicPaymentLink(slug);
  const payByLink = link ? null : await fetchPublicPayByLink(slug);

  return (
    <div className="flex flex-1 flex-col items-center bg-surface-container px-4 py-6 sm:py-16">
      <div className="w-full max-w-xl">
        <div
          aria-live="polite"
          className="overflow-hidden rounded-lg border border-outline-variant bg-surface shadow-sm"
        >
          {link ? (
            link.status === "ACTIVE" ? (
              <PaymentForm slug={slug} link={link} />
            ) : (
              <NonActiveState link={link} />
            )
          ) : payByLink ? (
            payByLink.is_active ? (
              <PayByLinkForm slug={slug} link={payByLink} />
            ) : (
              <StatusCard
                variant="unavailable"
                title="Payments are currently paused"
                message={`${payByLink.display_name} isn't accepting payments through this link right now. Please check back later.`}
              />
            )
          ) : (
            <StatusCard
              variant="unavailable"
              title="Link unavailable"
              message="This payment link doesn't exist. Double-check the link and try again."
            />
          )}
        </div>

        <p className="mt-6 flex items-center justify-center gap-1.5 text-center text-xs text-on-surface-variant">
          <LockIcon />
          Powered by InfinityPay
        </p>
      </div>
    </div>
  );
}

/**
 * Renders EXPIRED/CANCELLED/PAID — everything except the live ACTIVE form.
 * Callers only reach this once they've already checked status !== "ACTIVE";
 * the cast just documents that instead of re-deriving it structurally.
 */
function NonActiveState({ link }: { link: PublicPaymentLink }) {
  const copy = NON_ACTIVE_COPY[link.status as Exclude<PaymentLinkStatus, "ACTIVE">];

  return (
    <StatusCard
      variant={link.status.toLowerCase() as "expired" | "cancelled" | "paid"}
      title={copy.title}
      message={copy.message}
      summary={{ merchantName: link.merchant_name, amount: link.amount, currency: link.currency }}
    />
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" strokeWidth={2} stroke="currentColor" className="h-3.5 w-3.5">
      <rect x="4.5" y="10.5" width="15" height="9.75" rx="1.5" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 10.5V7.5a3.75 3.75 0 017.5 0v3" />
    </svg>
  );
}
