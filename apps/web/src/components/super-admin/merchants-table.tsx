"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { Icon } from "@/components/portal/icon";
import { StatusBadge } from "@/components/portal/status-badge";
import { formatCurrency, formatDateTime } from "@/lib/format";
import {
  approveMerchantAction,
  confirmMerchantEmailAction,
  correctMerchantContactEmailAction,
  resendMerchantVerificationAction,
  setMerchantStatusAction,
  type MerchantActionState,
} from "@/lib/admin/live-actions";
import { merchantStatusBadge } from "@/lib/admin/status-tones";
import type { Merchant } from "@/lib/admin/types";

const MERCHANT_ACTION_IDLE: MerchantActionState = { error: null, ok: false, message: null };

/** Must be a child of the <form>, per useFormStatus's own rule. */
function IconSubmit({
  icon,
  title,
  className,
}: {
  icon: string;
  title: string;
  className: string;
}) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      title={pending ? `${title}…` : title}
      aria-busy={pending}
      className={`p-1.5 disabled:opacity-60 ${className}`}
    >
      <Icon
        name={pending ? "progress_activity" : icon}
        className={`text-[18px] ${pending ? "animate-spin" : ""}`}
      />
    </button>
  );
}

function TextSubmit({
  idleLabel,
  pendingLabel,
  className,
  title,
  children,
}: {
  idleLabel: string;
  pendingLabel: string;
  className: string;
  /** Accessible name. Required when the button's content is an icon,
   *  because `idleLabel` is then empty and the control would otherwise
   *  have no name at all for a screen reader. */
  title?: string;
  /** Icon content in place of a text label. Existing callers pass none
   *  and keep their text. */
  children?: React.ReactNode;
}) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      title={title}
      aria-label={title}
      className={`${className} disabled:opacity-60`}
    >
      {pending ? pendingLabel : (children ?? idleLabel)}
    </button>
  );
}

/** The piece these buttons were missing: a completed action said nothing,
 * so a Suspend that had worked looked identical to one that had not. */
function ActionFeedback({ state }: { state: MerchantActionState }) {
  if (state.error) {
    return (
      <p className="mt-1 inline-flex items-start gap-1 text-xs text-error text-left max-w-[16rem]">
        <Icon name="error" className="text-[14px] shrink-0" />
        {state.error}
      </p>
    );
  }
  if (state.ok) {
    return (
      <p className="mt-1 inline-flex items-start gap-1 text-xs text-primary text-left max-w-[16rem]">
        <Icon name="check_circle" className="text-[14px] shrink-0" />
        {state.message ?? "Done."}
      </p>
    );
  }
  return null;
}

function ApproveMerchantForm({ merchantId }: { merchantId: string }) {
  const [state, formAction] = useActionState<MerchantActionState, FormData>(
    () => approveMerchantAction(merchantId),
    MERCHANT_ACTION_IDLE,
  );
  return (
    <>
      <form action={formAction} className="inline">
        <IconSubmit icon="check_circle" title="Approve" className="text-on-surface-variant hover:text-primary" />
      </form>
      <ActionFeedback state={state} />
    </>
  );
}

/** Suspension stops the business trading and ends its portal session, so
 * it asks first — an icon button one pixel from "open merchant" is too
 * easy to hit by accident for something with that effect. */
function SuspendMerchantForm({ merchantId, businessName }: { merchantId: string; businessName: string }) {
  const [confirming, setConfirming] = useState(false);
  const [state, formAction] = useActionState<MerchantActionState, FormData>(
    () => setMerchantStatusAction(merchantId, "suspended"),
    MERCHANT_ACTION_IDLE,
  );

  // On success the row re-renders from revalidated data as "suspended", so
  // this component unmounts and the Reactivate button takes its place —
  // the status badge flipping is the confirmation. A failure keeps the row
  // as it is, which is why the error has to be shown here, next to a
  // button that is still there to try again.
  return (
    <>
      {confirming ? (
        <form action={formAction} className="inline-flex items-center gap-2">
          <span className="text-xs text-on-surface-variant">Suspend {businessName}?</span>
          <TextSubmit
            idleLabel="Confirm"
            pendingLabel="Suspending…"
            className="px-2 py-1 rounded-md bg-error text-on-error text-xs font-semibold"
          />
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="px-2 py-1 rounded-md border border-surface-container-highest text-xs"
          >
            Cancel
          </button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          title="Suspend"
          className="p-1.5 text-on-surface-variant hover:text-error"
        >
          <Icon name="block" className="text-[18px]" />
        </button>
      )}
      <ActionFeedback state={state} />
    </>
  );
}

/** Fix a mistyped signup email.
 *
 * Every duplicate business in production was one merchant who mistyped
 * their address on the Get Started form, never received the verification
 * link, and signed up again - because "Resend verification email" was the
 * only thing on offer and it resends to the address that was already
 * wrong. Signup now refuses that second attempt, so this is the way out,
 * and it has to live where support is already looking at the business.
 *
 * Takes a typed address rather than a one-click action: there is nothing
 * to guess, and the new address stays unverified until the merchant
 * clicks the link, so a typo here fails closed. */
function CorrectEmailForm({ merchantId, currentEmail }: { merchantId: string; currentEmail: string | null }) {
  const [editing, setEditing] = useState(false);
  const [email, setEmail] = useState("");
  const [state, formAction] = useActionState<MerchantActionState, FormData>(
    () => correctMerchantContactEmailAction(merchantId, email),
    MERCHANT_ACTION_IDLE,
  );

  if (!editing) {
    return (
      <>
        <button
          type="button"
          onClick={() => {
            setEmail(currentEmail ?? "");
            setEditing(true);
          }}
          title="Correct signup email"
          className="p-1.5 text-on-surface-variant hover:text-primary"
        >
          <Icon name="alternate_email" className="text-[18px]" />
        </button>
        <ActionFeedback state={state} />
      </>
    );
  }

  return (
    <>
      <form action={formAction} className="inline-flex items-center gap-2">
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="correct@email.com"
          aria-label="Correct signup email"
          className="w-52 rounded-md border border-outline-variant bg-surface px-2 py-1 text-xs text-on-surface"
        />
        <TextSubmit
          idleLabel="Save"
          pendingLabel="Saving…"
          className="px-2 py-1 rounded-md bg-primary-container text-on-surface text-xs font-semibold"
        />
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="px-2 py-1 rounded-md border border-surface-container-highest text-xs"
        >
          Cancel
        </button>
      </form>
      <ActionFeedback state={state} />
    </>
  );
}

/** Helping a merchant who cannot get past email verification.
 *
 * Nine live businesses were stranded unable to sign in - approved, KYC
 * verified, wallet ready - because nobody had clicked the link in their
 * verification email. There was no way for Super Admin to help: the
 * only resend is self-service, reached from a "check your email" screen
 * a merchant who closed the tab weeks ago cannot get back to. The
 * fallback was hand-editing auth.users in the Supabase dashboard.
 *
 * Two buttons, deliberately unequal. Resend is the obvious one and
 * changes nothing. Confirming is an override of a security control, so
 * it asks first and says plainly what it gives up. */
function EmailVerificationActions({ merchantId }: { merchantId: string }) {
  const [confirming, setConfirming] = useState(false);
  const [resendState, resendAction] = useActionState<MerchantActionState, FormData>(
    () => resendMerchantVerificationAction(merchantId),
    MERCHANT_ACTION_IDLE,
  );
  const [confirmState, confirmAction] = useActionState<MerchantActionState, FormData>(
    () => confirmMerchantEmailAction(merchantId),
    MERCHANT_ACTION_IDLE,
  );

  return (
    <>
      <form action={resendAction} className="inline">
        <TextSubmit
          idleLabel=""
          pendingLabel="Sending…"
          title="Resend verification email"
          className="p-1.5 text-on-surface-variant hover:text-primary"
        >
          <Icon name="forward_to_inbox" className="text-[18px]" />
        </TextSubmit>
      </form>
      <ActionFeedback state={resendState} />

      {!confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          title="Mark email verified without them clicking the link"
          className="p-1.5 text-on-surface-variant hover:text-primary"
        >
          <Icon name="verified_user" className="text-[18px]" />
        </button>
      ) : (
        <form action={confirmAction} className="inline-flex items-center gap-2">
          {/* Said out loud, not buried in a tooltip. Confirming an
              address nobody has proved they can receive removes the
              only signal that the address is wrong. */}
          <span className="text-xs text-on-surface-variant">
            Mark verified without proof? Use “Correct signup email” instead if the address is wrong.
          </span>
          <TextSubmit
            idleLabel="Confirm"
            pendingLabel="Confirming…"
            className="px-2 py-1 rounded-md bg-primary-container text-on-surface text-xs font-semibold"
          />
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="px-2 py-1 rounded-md border border-surface-container-highest text-xs"
          >
            Cancel
          </button>
        </form>
      )}
      <ActionFeedback state={confirmState} />
    </>
  );
}

function ReactivateMerchantForm({ merchantId }: { merchantId: string }) {
  const [state, formAction] = useActionState<MerchantActionState, FormData>(
    () => setMerchantStatusAction(merchantId, "active"),
    MERCHANT_ACTION_IDLE,
  );
  return (
    <>
      <form action={formAction} className="inline">
        <IconSubmit icon="restart_alt" title="Reactivate" className="text-on-surface-variant hover:text-primary" />
      </form>
      <ActionFeedback state={state} />
    </>
  );
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function MerchantsTable({
  rows,
  initialSearch = "",
}: {
  rows: Merchant[];
  initialSearch?: string;
}) {
  // Seeded from ?search= so the topbar's search box has somewhere to
  // land. Without this the topbar would route here and the term would be
  // silently dropped, which looks identical to "no results".
  const [search, setSearch] = useState(initialSearch);
  const [statusFilter, setStatusFilter] = useState("All Statuses");

  const filtered = rows.filter((merchant) => {
    if (statusFilter !== "All Statuses") {
      const labels: Record<string, Merchant["account_status"]> = {
        Active: "active",
        "Pending Verification": "pending",
        Suspended: "suspended",
        Closed: "closed",
      };
      if (merchant.account_status !== labels[statusFilter]) return false;
    }
    if (search) {
      const needle = search.toLowerCase();
      const haystack = [
        merchant.business_name,
        merchant.merchant_code ?? "",
        merchant.email,
        merchant.login_email ?? "",
        merchant.contact_phone ?? "",
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });

  return (
    <>
      <Card>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <input
            className="sm:col-span-2 px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            placeholder="Search by ID, business name, email, or phone"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option>All Statuses</option>
            <option>Active</option>
            <option>Pending Verification</option>
            <option>Suspended</option>
            <option>Closed</option>
          </select>
        </div>
      </Card>

      <Card padded={false}>
        <div className="p-5 pb-3">
          <h3 className="text-2xl font-semibold text-on-background">All Merchants</h3>
        </div>
        {filtered.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">No merchants match your filters.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[900px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Merchant</th>
                  <th className={thClass}>Owner</th>
                  <th className={thClass}>Available Balance</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>Created</th>
                  <th className={`${thClass} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {filtered.map((merchant) => {
                  const badge = merchantStatusBadge(merchant.account_status);
                  return (
                    <tr
                      key={merchant.merchant_id}
                      className={`border-t border-surface-container-highest ${merchant.account_status === "suspended" ? "opacity-60" : ""}`}
                    >
                      <td className={tdClass}>
                        <Link
                          href={`/super-admin/merchants/${merchant.merchant_id}`}
                          className="flex items-center gap-3 hover:opacity-80"
                        >
                          <div className="w-9 h-9 rounded-full bg-primary-container/15 text-primary flex items-center justify-center font-bold text-xs shrink-0">
                            {initials(merchant.business_name)}
                          </div>
                          <div>
                            <div className="font-medium text-on-background">{merchant.business_name}</div>
                            {merchant.live_api_without_webhook && (
                              /* Taking real money with nowhere to send the
                                 notification. Shown here rather than as an
                                 alert because nothing fails - no URL means
                                 nothing is ever queued, so there is no
                                 delivery to report. The only way anyone
                                 learns is by being told. */
                              <div
                                className="mt-0.5 inline-flex items-center gap-1 text-xs font-medium text-error"
                                title="Live API key but no webhook URL — this partner is never told when a payment succeeds"
                              >
                                <Icon name="warning" className="text-[14px]" />
                                Live API, no webhook
                              </div>
                            )}
                            <div className="text-xs text-on-surface-variant">
                              {merchant.email}
                              {merchant.merchant_code && (
                                <>
                                  {" "}
                                  · <span className="font-mono">{merchant.merchant_code}</span>
                                </>
                              )}
                            </div>
                            {/* The address they sign in with, shown only
                              * when it differs from the contact address
                              * above - on most rows they are the same and
                              * a second identical line would be noise.
                              *
                              * Monospaced on purpose. In the body font a
                              * capital I and a lowercase l are the same
                              * glyph, which is the whole reason this line
                              * exists: an operator read a contact address
                              * aloud, the customer typed the other letter,
                              * and the login said "Incorrect email or
                              * password". */}
                            {merchant.login_email &&
                              merchant.login_email.toLowerCase() !== merchant.email?.toLowerCase() && (
                                <div className="text-xs text-on-surface-variant">
                                  <span className="font-semibold">Signs in as:</span>{" "}
                                  <span className="font-mono">{merchant.login_email}</span>
                                </div>
                              )}
                          </div>
                        </Link>
                      </td>
                      <td className={`${tdClass} text-on-surface-variant`}>{merchant.owner_name ?? "—"}</td>
                      <td className={`${tdClass} font-semibold text-on-background`}>
                        {formatCurrency(merchant.available_balance, "TZS")}
                      </td>
                      <td className={tdClass}>
                        <StatusBadge {...badge} />
                      </td>
                      <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(merchant.created_at)}</td>
                      <td className={`${tdClass} text-right whitespace-nowrap`}>
                        {merchant.account_status === "pending" && (
                          <ApproveMerchantForm merchantId={merchant.merchant_id} />
                        )}
                        {merchant.account_status === "active" && (
                          <SuspendMerchantForm
                            merchantId={merchant.merchant_id}
                            businessName={merchant.business_name}
                          />
                        )}
                        {merchant.account_status === "suspended" && (
                          <ReactivateMerchantForm merchantId={merchant.merchant_id} />
                        )}
                        <CorrectEmailForm
                          merchantId={merchant.merchant_id}
                          currentEmail={merchant.email ?? null}
                        />
                        <EmailVerificationActions merchantId={merchant.merchant_id} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
