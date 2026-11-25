"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useActionState, useEffect, useRef } from "react";

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

/** Field name -> the label the person actually sees.
 *
 * The summary has to name fields the way the form does. "nidaNumber"
 * in an error list is a developer's word for it and sends someone
 * hunting. */
const FIELD_LABELS: Record<string, string> = {
  businessName: "Business Name",
  ownerName: "Your Name",
  businessCategory: "Business Type",
  nidaNumber: "NIDA Number",
  businessEmail: "Email",
  businessPhone: "Business Phone",
  tinNumber: "TIN",
  password: "Password",
  confirmPassword: "Confirm Password",
  agreedToTerms: "Terms of Service",
  agreedToPrivacy: "Privacy Policy",
  confirmedAccurate: "Confirmation that your information is accurate",
};

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

function CreateAccountFormInner() {
  // useSearchParams rather than a prop: this page is a server component
  // and the code only matters to the form. Seeds the Referral Code field,
  // which stays editable - a visitor who arrived by link should not have
  // to retype it, and one who was told a code still needs to enter it.
  const referralCode = (useSearchParams().get("ref") ?? "").trim();

  const [state, action, pending] = useActionState(signupWithBusinessAction, null);
  const v = state?.values ?? {};
  const err = state?.errors ?? {};

  // Every field error renders inline, under its own field. That is the
  // right place for it and it was the only place for it, which made a
  // rejected signup look like a dead button: the submit control sits at
  // the very bottom of a long form, so someone pressing it sees
  // "Creating account…" flick back to "Create Account" while the actual
  // reason - "NIDA number is required." - is painted several hundred
  // pixels above the fold, out of sight.
  //
  // Reported as the form "getting stuck". Nothing was stuck; the answer
  // was just somewhere the person could not see.
  //
  // So on a failed submit: say so where they are looking, and take them
  // to the first field that needs them.
  const errorKeys = Object.keys(err);
  const summaryRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (errorKeys.length === 0) return;
    // The summary first - it is at the top of the form and names
    // everything wrong, which matters when more than one field failed.
    summaryRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    // Then the cursor into the first field that needs attention, so the
    // next keystroke goes somewhere useful. Focus is what actually
    // moves the page for a keyboard or screen-reader user; the scroll
    // above is for everyone else.
    const first = document.getElementById(errorKeys[0]);
    if (first instanceof HTMLInputElement) {
      first.focus({ preventScroll: true });
    }
    // Keyed on the state object: a second submit that fails the same way
    // must scroll again, and comparing error keys would not re-fire.
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps

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
      {errorKeys.length > 0 && (
        <div
          ref={summaryRef}
          role="alert"
          tabIndex={-1}
          className="rounded-lg border border-error/30 bg-error/10 px-4 py-3 text-sm text-error"
        >
          <p className="font-semibold">
            {errorKeys.length === 1
              ? "One thing needs fixing before we can create your account:"
              : `${errorKeys.length} things need fixing before we can create your account:`}
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 font-medium">
            {errorKeys.map((key) => (
              <li key={key}>
                {/* Linked, so a form this long is one click rather than
                    a hunt. */}
                <a href={`#${key}`} className="underline hover:no-underline">
                  {FIELD_LABELS[key] ?? key}
                </a>
                : {err[key]?.[0]}
              </li>
            ))}
          </ul>
        </div>
      )}

      {state?.formError && (
        <div role="alert" className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">
          <p>{state.formError}</p>
          {state.formErrorAction && (
            // The way out, as a link rather than a sentence telling them
            // one exists. Someone who has just been refused an account
            // will not go hunting through the site for the page that
            // unblocks them.
            <p className="mt-2">
              <Link href={state.formErrorAction.href} className="font-semibold underline hover:no-underline">
                {state.formErrorAction.label}
              </Link>
              <span className="font-normal">
                {" "}
                — or{" "}
                <Link href="/dashboard/login" className="font-semibold underline hover:no-underline">
                  sign in
                </Link>{" "}
                if you have already confirmed your email.
              </span>
            </p>
          )}
        </div>
      )}

      <fieldset className={fieldsetClass}>
        <legend className={legendClass}>Business details</legend>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field name="businessName" label="Business Name" defaultValue={v.businessName} errors={err.businessName} />
          <Field name="ownerName" label="Your Name" placeholder="e.g. Amani Mushi" defaultValue={v.ownerName} errors={err.ownerName} />
        </div>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field name="businessCategory" label="Business Type" placeholder="e.g. Retail, Logistics, Restaurant" defaultValue={v.businessCategory} errors={err.businessCategory} />
          <Field name="nidaNumber" label="NIDA Number" placeholder="20-digit National ID number" defaultValue={v.nidaNumber} errors={err.nidaNumber} />
        </div>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field name="businessEmail" label="Email" type="email" placeholder="hello@business.co.tz" defaultValue={v.businessEmail} errors={err.businessEmail} />
          <Field name="businessPhone" label="Business Phone" type="tel" placeholder="+255 7XX XXX XXX" defaultValue={v.businessPhone} errors={err.businessPhone} />
        </div>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <Field name="tinNumber" label="TIN" optional hideOptionalHint placeholder="Taxpayer Identification Number" defaultValue={v.tinNumber} errors={err.tinNumber} />
          <Field name="websiteOrAppLink" label="Website or App Link" optional placeholder="www.yourbusiness.co.tz" defaultValue={v.websiteOrAppLink} />
        </div>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          {/* Visible and editable, not hidden. A code arriving by
              WhatsApp or word of mouth needs somewhere to go, and the
              merchant portal tells referrers it can be typed in here.
              Prefilled from /create-account?ref=CODE so someone who
              followed a link never has to touch it. */}
          <div>
            <Field
              name="referralCode"
              label="Referral Code"
              optional
              placeholder="e.g. INF-VZ7K3M"
              // The re-rendered value after a failed submit wins over the
              // URL, so a typed code survives a validation bounce.
              defaultValue={v.referralCode ?? referralCode}
            />
            <p className="mt-1.5 text-xs text-on-surface-variant">
              If a business invited you to InfinityPay, enter their code here.
            </p>
          </div>
        </div>
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
        className="w-full inline-flex items-center justify-center gap-2 btn-brand text-sm font-medium px-8 py-3.5 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-[#087e8b] focus-visible:ring-offset-2"
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


/** useSearchParams opts a component into client-side rendering, which
 * Next requires a Suspense boundary for on an otherwise static route.
 * The fallback is null because the form is below the fold of its own
 * heading and a skeleton would flash on every load. */
export function CreateAccountForm() {
  return (
    <Suspense fallback={null}>
      <CreateAccountFormInner />
    </Suspense>
  );
}
