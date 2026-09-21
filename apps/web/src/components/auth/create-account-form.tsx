"use client";

import Link from "next/link";
import { useActionState } from "react";

import { SERVICE_NEEDED_LABELS, ServiceNeeded } from "@infinity/shared";

import { resendVerificationAction, signupWithBusinessAction } from "@/lib/auth/actions";

const inputClass =
  "w-full border-0 border-b border-outline-variant bg-transparent pb-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container transition-colors";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2";
const errorClass = "mt-1.5 text-xs font-medium text-error";
const sectionHeadingClass = "text-base font-semibold text-on-surface";

// Dynamic QR is a real collection method once onboarded — just not an
// interest checkbox during signup (mirrors OnboardingForm).
const SERVICES = Object.values(ServiceNeeded).filter((service) => service !== ServiceNeeded.DYNAMIC_QR);

function Field({
  name,
  label,
  type = "text",
  placeholder,
  optional,
  autoComplete,
  defaultValue,
  errors,
}: {
  name: string;
  label: string;
  type?: string;
  placeholder?: string;
  optional?: boolean;
  autoComplete?: string;
  defaultValue?: string;
  errors?: string[];
}) {
  return (
    <div>
      <label htmlFor={name} className={labelClass}>
        {label}
        {optional && <span className="normal-case font-normal text-outline"> (optional)</span>}
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
        <Link href="/merchant/login" className="font-semibold text-primary-container hover:underline">
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

      <section className="space-y-6">
        <h2 className={sectionHeadingClass}>Your account</h2>
        <div className="grid sm:grid-cols-2 gap-6">
          <Field name="fullName" label="Your Name" autoComplete="name" placeholder="e.g. Amani Mushi" defaultValue={v.fullName} errors={err.fullName} />
          <Field name="email" label="Email Address" type="email" autoComplete="off" placeholder="you@business.co.tz" defaultValue={v.email} errors={err.email} />
          <Field name="phone" label="Phone Number" type="tel" autoComplete="tel" placeholder="+255 7XX XXX XXX" defaultValue={v.phone} errors={err.phone} />
          <Field name="nidaNumber" label="NIDA Number" placeholder="20-digit National ID number" defaultValue={v.nidaNumber} errors={err.nidaNumber} />
        </div>
        <div className="grid sm:grid-cols-2 gap-6">
          <div>
            <Field name="password" label="Password" type="password" autoComplete="new-password" errors={err.password} />
            <p className="mt-1.5 text-xs text-on-surface-variant">
              At least 8 characters, with uppercase, lowercase, a number, and a symbol.
            </p>
          </div>
          <Field name="confirmPassword" label="Confirm Password" type="password" autoComplete="new-password" errors={err.confirmPassword} />
        </div>
      </section>

      <section className="space-y-6">
        <h2 className={sectionHeadingClass}>Your business</h2>
        <div className="grid sm:grid-cols-2 gap-6">
          <Field name="businessName" label="Business Name" defaultValue={v.businessName} errors={err.businessName} />
          <Field name="businessCategory" label="Business Category" placeholder="e.g. Retail, Logistics, Restaurant" defaultValue={v.businessCategory} errors={err.businessCategory} />
        </div>
        <Field name="natureOfBusiness" label="Nature of Business" placeholder="Briefly describe what your business does" defaultValue={v.natureOfBusiness} errors={err.natureOfBusiness} />
        <div className="grid sm:grid-cols-2 gap-6">
          <Field name="physicalAddress" label="Physical Address" defaultValue={v.physicalAddress} errors={err.physicalAddress} />
          <Field name="regionCity" label="Region / City" defaultValue={v.regionCity} errors={err.regionCity} />
        </div>
        <Field name="websiteOrAppLink" label="Website or App Link" optional placeholder="www.yourbusiness.co.tz" defaultValue={v.websiteOrAppLink} />

        <div>
          <label htmlFor="tinCertificate" className={labelClass}>
            TIN Certificate <span className="normal-case font-normal text-outline">(optional)</span>
          </label>
          <input
            id="tinCertificate"
            name="tinCertificate"
            type="file"
            accept="application/pdf,image/jpeg,image/png"
            className="w-full text-xs text-on-surface-variant file:mr-3 file:rounded-lg file:border-0 file:bg-surface-container file:px-3 file:py-2 file:text-xs file:font-medium file:text-on-surface"
          />
          <p className="mt-1.5 text-xs text-on-surface-variant">PDF, JPG, or PNG. You can also send this later if you don&apos;t have it now.</p>
          {err.tinCertificate?.map((msg) => (
            <p key={msg} className={errorClass}>
              {msg}
            </p>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <h2 className={sectionHeadingClass}>Services needed</h2>
        <div className="grid sm:grid-cols-2 gap-3">
          {SERVICES.map((service) => (
            <label key={service} className="flex items-center gap-3 text-sm text-on-surface">
              <input
                type="checkbox"
                name="servicesNeeded"
                value={service}
                defaultChecked
                className="h-4 w-4 rounded border-outline-variant text-primary-container focus:ring-primary-container"
              />
              {SERVICE_NEEDED_LABELS[service]}
            </label>
          ))}
        </div>
        {err.servicesNeeded?.map((msg) => (
          <p key={msg} className={errorClass}>
            {msg}
          </p>
        ))}
      </section>

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
        <Link href="/merchant/login" className="font-semibold text-primary-container hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
