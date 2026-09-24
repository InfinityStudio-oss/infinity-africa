"use client";

import Link from "next/link";
import { useActionState } from "react";

import { resendVerificationAction, signupWithBusinessAction } from "@/lib/auth/actions";

// Boxed inputs inside bordered fieldsets — each field reads as its own
// control rather than a line on a page, which is what makes a long
// signup form scannable. InfinityPay's own colour tokens throughout; only
// the layout is borrowed.
const inputClass =
  "mt-1.5 w-full rounded-lg border border-outline-variant bg-surface px-3 py-2 text-sm text-on-surface placeholder-outline transition-colors focus:border-primary-container focus:outline-none focus:ring-2 focus:ring-primary-container/40";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide";
const errorClass = "mt-1.5 text-xs font-medium text-error";
const fieldsetClass = "rounded-xl border border-outline-variant bg-surface p-6";
const legendClass = "px-1 text-sm font-bold text-on-surface";

function Field({
  name,
  label,
  type = "text",
  placeholder,
  optional,
  hideOptionalHint,
  autoComplete,
  defaultValue,
  errors,
}: {
  name: string;
  label: string;
  type?: string;
  placeholder?: string;
  optional?: boolean;
  /** Optional, but without the "(optional)" hint — for fields where the
   *  absence of the required asterisk is signal enough. */
  hideOptionalHint?: boolean;
  autoComplete?: string;
  defaultValue?: string;
  errors?: string[];
}) {
  return (
    <div>
      <label htmlFor={name} className={labelClass}>
        {label}
        {optional ? (
          hideOptionalHint ? null : <span className="normal-case font-normal text-outline"> (optional)</span>
        ) : (
          <span aria-hidden className="text-error"> *</span>
        )}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        placeholder={placeholder}
        autoComplete={autoComplete}
        defaultValue={defaultValue}
        className={inputClass}
      />
      {errors?.map((msg) => (
        <p key={msg} className={errorClass}>
          {msg}
        </p>
      ))}
    </div>
  );
}

function SignupComplete({ email, notice, canResend }: { email: string; notice?: string; canResend: boolean }) {
  const [resendState, resendAction, resending] = useActionState(resendVerificationAction, null);

  return (
    <div className="mt-8 space-y-4">
      <div className="rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
        {resendState?.notice ?? notice ?? "Account created. Your business details have been submitted for review."}
      </div>

      {resendState?.formError && (
        <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">{resendState.formError}</div>
      )}

      {canResend && (
        <>
          <p className="text-sm text-on-surface-variant">
            We sent a verification link to <span className="font-semibold text-on-surface">{email}</span>. Confirm your
            email, then wait for InfinityPay to review and approve your account. The link can take a minute to
            arrive — check your spam folder too.
          </p>
          <form action={resendAction}>
            <input type="hidden" name="email" value={email} />
            <button
              type="submit"
              disabled={resending}
              className="w-full inline-flex items-center justify-center gap-2 border border-outline-variant text-on-surface text-sm font-medium px-8 py-3 rounded-lg hover:bg-surface-container transition-colors disabled:opacity-60"
            >
              {resending ? "Sending…" : "Resend verification email"}
            </button>
          </form>
        </>
      )}

      <p className="text-center text-sm text-on-surface-variant">
        {canResend ? "Already verified? " : ""}
        <Link href="/dashboard/login" className="font-semibold text-primary-container hover:underline">
          {canResend ? "Sign in" : "Back to login"}
        </Link>
      </p>
    </div>
  );
}

export function CreateAccountForm() {
  const [state, action, pending] = useActionState(signupWithBusinessAction, null);
  const v = state?.values ?? {};
  const err = state?.errors ?? {};

  if (state?.notice) {
    return (
      <SignupComplete
        email={v.email ?? ""}
        notice={state.notice}
        canResend={Boolean(state.awaitingEmailVerification)}
      />
    );
  }

  return (
    <form action={action} className="mt-8 space-y-9">
      {state?.formError && (
        <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">{state.formError}</div>
      )}

      <fieldset className={fieldsetClass}>
        <legend className={legendClass}>Business details</legend>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field name="businessName" label="Business / Trading Name" defaultValue={v.businessName} errors={err.businessName} />
          <Field name="legalBusinessName" label="Legal Business Name" optional hideOptionalHint defaultValue={v.legalBusinessName} errors={err.legalBusinessName} />
        </div>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field name="businessCategory" label="Business Type" placeholder="e.g. Retail, Logistics, Restaurant" defaultValue={v.businessCategory} errors={err.businessCategory} />
          <Field name="nidaNumber" label="NIDA Number" placeholder="20-digit National ID number" defaultValue={v.nidaNumber} errors={err.nidaNumber} />
        </div>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field name="businessEmail" label="Business Email" type="email" placeholder="hello@business.co.tz" defaultValue={v.businessEmail} errors={err.businessEmail} />
          <Field name="businessPhone" label="Business Phone" type="tel" placeholder="+255 7XX XXX XXX" defaultValue={v.businessPhone} errors={err.businessPhone} />
        </div>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field name="tinNumber" label="TIN" optional hideOptionalHint placeholder="Taxpayer Identification Number" defaultValue={v.tinNumber} errors={err.tinNumber} />
          <Field name="websiteOrAppLink" label="Website or App Link" optional placeholder="www.yourbusiness.co.tz" defaultValue={v.websiteOrAppLink} />
        </div>
      </fieldset>

      {/* Business Email above is the login email — there is no separate
          account-owner email any more, so this section only has to collect
          the password that goes with it. */}
      <fieldset className={fieldsetClass}>
        <legend className={legendClass}>Create your password</legend>
        <p className="mt-2 text-sm text-on-surface-variant">
          You&apos;ll sign in with your business email and this password.
        </p>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <div>
            <Field name="password" label="Password" type="password" autoComplete="new-password" errors={err.password} />
            <p className="mt-1.5 text-xs text-on-surface-variant">
              At least 8 characters, with uppercase, lowercase, a number, and a symbol.
            </p>
          </div>
          <Field name="confirmPassword" label="Confirm Password" type="password" autoComplete="new-password" errors={err.confirmPassword} />
        </div>
      </fieldset>

      <section className="space-y-3">
        {[
          {
            name: "agreedToTerms",
            node: (
              <span>
                I agree to the InfinityPay{" "}
                <Link href="/terms" target="_blank" className="font-semibold text-primary-container hover:underline">
                  Terms of Service
                </Link>
              </span>
            ),
          },
          {
            name: "agreedToPrivacy",
            node: (
              <span>
                I agree to the InfinityPay{" "}
                <Link href="/privacy" target="_blank" className="font-semibold text-primary-container hover:underline">
                  Privacy Policy
                </Link>
              </span>
            ),
          },
          { name: "confirmedAccurate", node: <span>I confirm that the information provided is accurate</span> },
        ].map((item) => (
          <div key={item.name}>
            <label className="flex items-start gap-3 text-sm text-on-surface">
              <input
                type="checkbox"
                name={item.name}
                className="mt-0.5 h-4 w-4 rounded border-outline-variant text-primary-container focus:ring-primary-container"
              />
              {item.node}
            </label>
            {err[item.name]?.map((msg) => (
              <p key={msg} className={errorClass}>
                {msg}
              </p>
            ))}
          </div>
        ))}
      </section>

      <button
        type="submit"
        disabled={pending}
        className="w-full inline-flex items-center justify-center gap-2 bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
      >
        {pending ? "Creating account…" : "Create Account"}
      </button>

      <p className="text-center text-sm text-on-surface-variant">
        Already have an account?{" "}
        <Link href="/dashboard/login" className="font-semibold text-primary-container hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
