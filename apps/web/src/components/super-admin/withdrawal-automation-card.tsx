"use client";

import { useActionState, useState } from "react";

import { Icon } from "@/components/portal/icon";
import { saveWithdrawalAutomationPolicyAction } from "@/lib/admin/live-actions";
import {
  EMPTY_POLICY_STATE,
  type PolicyActionState,
  type WithdrawalAutomationPolicy,
} from "@/lib/admin/types";

/**
 * Automatic Withdrawal Controls.
 *
 * Sits above the approval queue because it decides how much of that queue
 * there is going to be. Four rules shape everything here:
 *
 * 1. **The effective state is the headline, not the stored switch.** A
 *    deployment override can force manual approval while the stored
 *    policy says ON. Showing a green switch then would be a lie about
 *    money, so the status line reads from `automation_active` and the
 *    override gets its own explanation.
 * 2. **Amounts stay strings.** They arrive as decimal strings and go back
 *    as decimal strings. Nothing here calls Number() on a limit except to
 *    format the worked example, and that result is never submitted.
 * 3. **Widening asks; tightening does not.** Turning automation on or
 *    raising a limit needs a confirmation that states the effective
 *    limits. Turning it off is one click — an operator reaching for the
 *    brake must not be asked twice.
 * 4. **Eligibility is not approval.** The pending queue below is separate
 *    and stays separate; nothing on this card implies a waiting request
 *    will be paid.
 */

const EXPLAIN_ENABLED =
  "When enabled, eligible merchant withdrawal requests within these limits can be processed " +
  "automatically after required verification and OTP. Other requests require manual approval.";

const EXPLAIN_DISABLED =
  "When disabled, requests require manual approval. Payouts already submitted to the provider " +
  "continue through reconciliation.";

/** Group a decimal string for display without going through a float.
 * `formatCurrency` would be the obvious choice, but it parses; this keeps
 * the operator's own digits intact in the worked example they are reading
 * to decide what the limit means. */
function groupDecimalString(value: string): string | null {
  const trimmed = value.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return null;
  const [whole, fraction] = trimmed.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction ? `${grouped}.${fraction}` : grouped;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1.5">
        {label}
      </label>
      {children}
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-outline-variant bg-transparent px-3 py-2 text-sm text-on-surface " +
  "placeholder-outline focus:outline-none focus:border-primary-container disabled:opacity-50";

export function WithdrawalAutomationCard({ policy }: { policy: WithdrawalAutomationPolicy | null }) {
  const [state, formAction, isPending] = useActionState<PolicyActionState, FormData>(
    saveWithdrawalAutomationPolicyAction,
    EMPTY_POLICY_STATE,
  );

  // The saved policy wins over the one the page was rendered with, so the
  // card shows the new version number immediately rather than only after
  // the revalidated page arrives.
  const current = state.policy ?? policy;

  if (!current) {
    return (
      <div className="rounded-xl border border-error/40 bg-error/5 px-4 py-3 flex items-start gap-3">
        <Icon name="warning" className="text-error text-[20px] mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-on-background">Automatic withdrawal controls unavailable</p>
          <p className="text-xs text-on-surface-variant mt-0.5">
            The automation policy could not be loaded, so it cannot be shown or changed here. Withdrawals are
            going to manual approval in the meantime, which is the safe fallback. Reload to try again.
          </p>
        </div>
      </div>
    );
  }

  return (
    <PolicyEditor
      key={current.version ?? "unversioned"}
      current={current}
      state={state}
      formAction={formAction}
      isPending={isPending}
    />
  );
}

function PolicyEditor({
  current,
  state,
  formAction,
  isPending,
}: {
  current: WithdrawalAutomationPolicy;
  state: PolicyActionState;
  formAction: (formData: FormData) => void;
  isPending: boolean;
}) {
  const [enabled, setEnabled] = useState(current.enabled);
  const [maxAmount, setMaxAmount] = useState(current.max_amount_tzs ?? "");
  const [rolling, setRolling] = useState(current.merchant_rolling_24h_limit_tzs ?? "");
  const [confirming, setConfirming] = useState(false);

  const locked = current.manual_only_override || !current.deployment_automation_allowed;

  // Only a change that lets MORE money move unattended needs confirming.
  // Mirrors withdrawal_policy.requires_confirmation on the backend, which
  // is the enforcement — this only decides whether to show the step.
  const widening =
    (enabled && !current.enabled) ||
    (enabled &&
      (compareDecimalStrings(maxAmount, current.max_amount_tzs) > 0 ||
        compareDecimalStrings(rolling, current.merchant_rolling_24h_limit_tzs) > 0));

  const example = groupDecimalString(maxAmount);

  const statusTone = current.automation_active
    ? "border-primary-container/50 bg-primary-container/10"
    : "border-outline-variant bg-surface-container-lowest";

  return (
    <div className={`rounded-xl border ${statusTone}`}>
      <div className="px-5 py-4 border-b border-outline-variant/60 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Icon
            name={current.automation_active ? "bolt" : "gavel"}
            className={`text-[20px] mt-0.5 ${current.automation_active ? "text-primary" : "text-on-surface-variant"}`}
          />
          <div>
            <h3 className="text-sm font-semibold text-on-background">Automatic Withdrawal Controls</h3>
            {/* The effective state, never the stored switch. */}
            <p
              className={`text-sm font-semibold mt-0.5 ${
                current.automation_active ? "text-primary" : "text-on-surface-variant"
              }`}
            >
              {current.automation_active ? "Automatic processing enabled" : "Manual approval"}
            </p>
            <p className="text-xs text-on-surface-variant mt-1 max-w-xl">
              {current.automation_active ? EXPLAIN_ENABLED : EXPLAIN_DISABLED}
            </p>
          </div>
        </div>
        <div className="text-xs text-on-surface-variant text-right">
          {current.version !== null && <p>Policy version {current.version}</p>}
          {current.updated_at && (
            <p className="mt-0.5">
              Updated {new Date(current.updated_at).toLocaleString()}
              {current.updated_by_email ? ` by ${current.updated_by_email}` : ""}
            </p>
          )}
          {!current.updated_at && <p className="mt-0.5">Never changed</p>}
        </div>
      </div>

      {locked && (
        <div className="mx-5 mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 flex items-start gap-2">
          <Icon name="lock" className="text-amber-600 text-[18px] mt-0.5" />
          <p className="text-xs text-on-surface-variant">
            {current.blocked_explanation ??
              "A deployment setting is preventing automatic processing from being enabled here."}
          </p>
        </div>
      )}

      <form action={formAction} className="px-5 py-4 space-y-4">
        <input type="hidden" name="version" value={current.version ?? ""} />
        <input type="hidden" name="enabled" value={enabled ? "true" : "false"} />
        <input type="hidden" name="confirm" value={confirming ? "true" : "false"} />

        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-on-background">Automatic processing</p>
            <p className="text-xs text-on-surface-variant mt-0.5">
              Switching this off takes effect on the next payout decision. It does not cancel payouts already
              sent to the provider.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label="Automatic processing"
            disabled={locked || isPending}
            onClick={() => {
              setEnabled((on) => !on);
              setConfirming(false);
            }}
            className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
              enabled ? "bg-primary-container" : "bg-surface-container-highest"
            }`}
          >
            <span
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-surface transition-transform ${
                enabled ? "translate-x-[22px]" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <Row label="Maximum automatic withdrawal amount — inclusive">
            <input
              name="max_amount_tzs"
              value={maxAmount}
              onChange={(e) => {
                setMaxAmount(e.target.value);
                setConfirming(false);
              }}
              inputMode="decimal"
              disabled={isPending}
              className={inputClass}
              placeholder="e.g. 500000"
            />
            <p className="text-xs text-on-surface-variant mt-1.5">
              {example ? (
                <>
                  TZS {example} or less may process automatically; amounts above TZS {example} require
                  approval.
                </>
              ) : (
                "Enter an amount in TZS, to at most 2 decimal places."
              )}
            </p>
            <p className="text-[11px] text-outline mt-1">
              Applies to the requested payout amount. The balance check still has to cover the full wallet
              debit, including fees.
            </p>
          </Row>

          <Row label="Rolling 24-hour automatic limit per merchant">
            <input
              name="merchant_rolling_24h_limit_tzs"
              value={rolling}
              onChange={(e) => {
                setRolling(e.target.value);
                setConfirming(false);
              }}
              inputMode="decimal"
              disabled={isPending}
              className={inputClass}
              placeholder="e.g. 1000000"
            />
            <p className="text-xs text-on-surface-variant mt-1.5">
              Total this platform will process automatically for one merchant in any rolling 24 hours. Not a
              calendar day, and not reset by switching this off and on.
            </p>
          </Row>
        </div>

        {/* The deployment ceilings, shown only when they actually bite —
            otherwise this is noise on a screen that needs to be read
            quickly. */}
        {(compareDecimalStrings(maxAmount, current.hard_max_amount_tzs) > 0 ||
          compareDecimalStrings(rolling, current.hard_rolling_24h_limit_tzs) > 0) && (
          <p className="text-xs text-amber-600">
            This deployment caps automatic processing at TZS{" "}
            {groupDecimalString(current.hard_max_amount_tzs) ?? current.hard_max_amount_tzs} per withdrawal and
            TZS {groupDecimalString(current.hard_rolling_24h_limit_tzs) ?? current.hard_rolling_24h_limit_tzs}{" "}
            per merchant per 24 hours. A higher number here will be held to those.
          </p>
        )}

        {confirming && (
          <div className="rounded-lg border border-outline-variant bg-surface-container-low px-3 py-3">
            <p className="text-sm font-semibold text-on-background">Confirm these limits</p>
            <p className="text-xs text-on-surface-variant mt-1">
              This allows more money to be paid out without a Super Admin approving it. After saving:
            </p>
            <ul className="text-xs text-on-surface-variant mt-2 space-y-1 list-disc pl-4">
              <li>Automatic processing: {enabled ? "ON" : "OFF"}</li>
              <li>Up to TZS {example ?? maxAmount} per withdrawal, inclusive</li>
              <li>Up to TZS {groupDecimalString(rolling) ?? rolling} per merchant per rolling 24 hours</li>
            </ul>
            <p className="text-xs text-on-surface-variant mt-2">
              Verification, OTP, fraud checks, balance and destination rules still apply to every withdrawal.
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          {widening && !confirming ? (
            <button
              type="button"
              disabled={isPending}
              onClick={() => setConfirming(true)}
              className="rounded-lg bg-primary-container px-4 py-2 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-50"
            >
              Review and save
            </button>
          ) : (
            <button
              type="submit"
              disabled={isPending}
              className="rounded-lg bg-primary-container px-4 py-2 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-50"
            >
              {isPending ? "Saving…" : confirming ? "Confirm and save" : "Save"}
            </button>
          )}
          {confirming && (
            <button
              type="button"
              disabled={isPending}
              onClick={() => setConfirming(false)}
              className="rounded-lg border border-outline-variant px-4 py-2 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-low disabled:opacity-50"
            >
              Cancel
            </button>
          )}

          {/* A failed save says so and says nothing changed. The silent
              `<form action>` failure this avoids is the same one that made
              Approve and Reconcile look dead on this page. */}
          {!isPending && state.error && (
            <p className={`text-xs font-medium ${state.conflict ? "text-amber-600" : "text-error"}`}>
              {state.conflict
                ? `${state.error} Reload the page to see the current settings.`
                : `${state.error} Nothing was changed.`}
            </p>
          )}
          {!isPending && state.ok && state.message && (
            <p className="text-xs font-medium text-primary">{state.message}</p>
          )}
        </div>
      </form>
    </div>
  );
}

/** Compare two decimal strings without parsing either into a float.
 *
 * Returns 1, -1 or 0, and 0 for anything it cannot read as a plain
 * decimal — an unparseable value must not look like an increase and
 * trigger a confirmation step for a change that is not happening. The
 * backend is the enforcement either way.
 */
export function compareDecimalStrings(a: string | null, b: string | null): number {
  if (!a || !b) return 0;
  const pattern = /^\d+(\.\d+)?$/;
  const left = a.trim();
  const right = b.trim();
  if (!pattern.test(left) || !pattern.test(right)) return 0;

  const [leftWhole, leftFraction = ""] = left.split(".");
  const [rightWhole, rightFraction = ""] = right.split(".");

  const lw = leftWhole.replace(/^0+(?=\d)/, "");
  const rw = rightWhole.replace(/^0+(?=\d)/, "");
  if (lw.length !== rw.length) return lw.length > rw.length ? 1 : -1;
  if (lw !== rw) return lw > rw ? 1 : -1;

  const width = Math.max(leftFraction.length, rightFraction.length);
  const lf = leftFraction.padEnd(width, "0");
  const rf = rightFraction.padEnd(width, "0");
  if (lf === rf) return 0;
  return lf > rf ? 1 : -1;
}
