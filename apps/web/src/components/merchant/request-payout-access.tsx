"use client";

import { useState } from "react";

import { Icon } from "@/components/portal/icon";
import { requestPayoutAccess } from "@/lib/portal/api";

/**
 * The way out of a dead end.
 *
 * The Payouts page used to say "contact InfinityPay support to start in
 * the sandbox" and give no way to do it — no address, no button. The
 * only merchants who ever asked were the ones who already knew someone,
 * which is not a product.
 *
 * Asking grants nothing. It puts the merchant in the Super Admin queue
 * with every flag still off, and a human decides. The copy says so,
 * because a button that looks like self-service and then does nothing
 * visible for a day is worse than no button.
 */
export function RequestPayoutAccess({ alreadyRequestedAt }: { alreadyRequestedAt?: string | null }) {
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">(
    alreadyRequestedAt ? "sent" : "idle",
  );
  const [error, setError] = useState<string | null>(null);

  async function send() {
    setState("sending");
    setError(null);
    try {
      await requestPayoutAccess();
      setState("sent");
    } catch (err) {
      setState("failed");
      setError(err instanceof Error ? err.message : "Couldn't send the request. Try again.");
    }
  }

  if (state === "sent") {
    return (
      <div className="mt-5 inline-flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-left">
        <Icon name="check_circle" className="text-[18px] text-emerald-700 shrink-0 mt-0.5" />
        <p className="text-sm">
          <span className="font-semibold">Request sent.</span> InfinityPay will review it and switch
          on the sandbox for you. You will see this page change when they do.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-5">
      <button
        type="button"
        onClick={send}
        disabled={state === "sending"}
        className="btn-brand inline-flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-[#087e8b] focus-visible:ring-offset-2 disabled:cursor-wait"
      >
        {state === "sending" ? "Sending…" : "Request payout access"}
      </button>
      <p className="mt-2 text-xs text-on-surface-variant">
        Starts in the sandbox, where no real money moves. A person reviews every request.
      </p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
