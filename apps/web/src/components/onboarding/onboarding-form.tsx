"use client";

import Link from "next/link";
import { useActionState } from "react";

import { AccountStatus, SERVICE_NEEDED_LABELS, ServiceNeeded } from "@infinity/shared";

import { submitOnboardingAction } from "@/lib/onboarding/actions";

const inputClass =
  "w-full border-0 border-b border-outline-variant bg-transparent pb-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container transition-colors";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2";
const errorClass = "mt-1.5 text-xs font-medium text-error";
const sectionHeadingClass = "text-lg font-semibold text-on-surface";

// Dynamic QR is a real collection method merchants can still use once
// onboarded (see /v1/merchant/collections/dynamic-qr) — it's just not
// offered as a "services needed" interest checkbox during onboarding.
const SERVICES = Object.values(ServiceNeeded).filter((service) => service !== ServiceNeeded.DYNAMIC_QR);

export function OnboardingForm({
  accountStatus,
  defaultPhone,
}: {
  accountStatus: AccountStatus | null;
  // The phone number on file from signup — pre-fills the field below so a
  // merchant whose number is already valid doesn't have to retype it, but
  // stays editable since this is the only chance to fix it before
  // submission (submitOnboardingAction sends whatever's in this field, not
  // the account's stored value directly — see its own comment).
  defaultPhone: string;
}) {
  const [state, action, pending] = useActionState(submitOnboardingAction, null);
  const values = state?.values ?? {
    businessName: "",
    natureOfBusiness: "",
    businessCategory: "",
    physicalAddress: "",
    regionCity: "",
    nidaNumber: "",
    websiteOrAppLink: "",
    contactPhone: defaultPhone,
  };

  const needsResubmission = accountStatus === AccountStatus.REJECTED || accountStatus === AccountStatus.INFO_REQUESTED;

  return (
    <form action={action} className="space-y-10">
      {state?.formError && (
        <div className="rounded-lg bg-error/10 px-4 py-3 text-sm text-error">
          <p className="font-semibold">{state.formError}</p>
        </div>
      )}

      {needsResubmission && (
        <div className="rounded-lg bg-error/10 px-4 py-3 text-sm text-error">
          <p className="font-semibold">
            {accountStatus === AccountStatus.REJECTED
              ? "Your previous submission was rejected."
              : "More information was requested."}
          </p>
          <p className="mt-1">Please review and resubmit your details below.</p>
        </div>
      )}

      <section className="space-y-6">
        <h2 className={sectionHeadingClass}>Business Details</h2>
        <div className="grid sm:grid-cols-2 gap-7">
          <div>
            <label htmlFor="businessName" className={labelClass}>
              Business Name
            </label>
            <input id="businessName" name="businessName" type="text" defaultValue={values.businessName} className={inputClass} />
            {state?.errors?.businessName?.map((msg) => (
              <p key={msg} className={errorClass}>
                {msg}
              </p>
            ))}
          </div>
          <div>
            <label htmlFor="businessCategory" className={labelClass}>
              Business Category
            </label>
            <input
              id="businessCategory"
              name="businessCategory"
              type="text"
              placeholder="e.g. Retail, Logistics, Restaurant"
              defaultValue={values.businessCategory}
              className={inputClass}
            />
            {state?.errors?.businessCategory?.map((msg) => (
              <p key={msg} className={errorClass}>
                {msg}
              </p>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="natureOfBusiness" className={labelClass}>
            Nature of Business
          </label>
          <input
            id="natureOfBusiness"
            name="natureOfBusiness"
            type="text"
            placeholder="Briefly describe what your business does"
            defaultValue={values.natureOfBusiness}
            className={inputClass}
          />
          {state?.errors?.natureOfBusiness?.map((msg) => (
            <p key={msg} className={errorClass}>
              {msg}
            </p>
          ))}
        </div>

        <div className="grid sm:grid-cols-2 gap-7">
          <div>
            <label htmlFor="physicalAddress" className={labelClass}>
              Physical Address
            </label>
            <input id="physicalAddress" name="physicalAddress" type="text" defaultValue={values.physicalAddress} className={inputClass} />
            {state?.errors?.physicalAddress?.map((msg) => (
              <p key={msg} className={errorClass}>
                {msg}
              </p>
            ))}
          </div>
          <div>
            <label htmlFor="regionCity" className={labelClass}>
              Region / City
            </label>
            <input id="regionCity" name="regionCity" type="text" defaultValue={values.regionCity} className={inputClass} />
            {state?.errors?.regionCity?.map((msg) => (
              <p key={msg} className={errorClass}>
                {msg}
              </p>
            ))}
          </div>
        </div>

        <div className="grid sm:grid-cols-2 gap-7">
          <div>
            <label htmlFor="contactPhone" className={labelClass}>
              Contact Phone Number
            </label>
            <input
              id="contactPhone"
              name="contactPhone"
              type="tel"
              placeholder="e.g. 0747730270"
              defaultValue={values.contactPhone}
              className={inputClass}
            />
            {state?.errors?.contactPhone?.map((msg) => (
              <p key={msg} className={errorClass}>
                {msg}
              </p>
            ))}
          </div>
          <div>
            <label htmlFor="nidaNumber" className={labelClass}>
              NIDA Number
            </label>
            <input
              id="nidaNumber"
              name="nidaNumber"
              type="text"
              placeholder="20-digit National ID number"
              defaultValue={values.nidaNumber}
              className={inputClass}
            />
            {state?.errors?.nidaNumber?.map((msg) => (
              <p key={msg} className={errorClass}>
                {msg}
              </p>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="websiteOrAppLink" className={labelClass}>
            Website or App Link <span className="normal-case font-normal text-outline">(optional)</span>
          </label>
          <input
            id="websiteOrAppLink"
            name="websiteOrAppLink"
            type="text"
            placeholder="e.g. www.yourbusiness.co.tz"
            defaultValue={values.websiteOrAppLink}
            className={inputClass}
          />
        </div>
      </section>

      <section className="space-y-4">
        <h2 className={sectionHeadingClass}>Services Needed</h2>
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
        {state?.errors?.servicesNeeded?.map((msg) => (
          <p key={msg} className={errorClass}>
            {msg}
          </p>
        ))}
        <p className="text-sm text-on-surface-variant bg-surface-container rounded-lg px-4 py-3">
          After verification, merchants can withdraw collected funds from the merchant portal.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className={sectionHeadingClass}>Legal</h2>
        <label className="flex items-start gap-3 text-sm text-on-surface">
          <input
            type="checkbox"
            name="agreedToTerms"
            className="mt-0.5 h-4 w-4 rounded border-outline-variant text-primary-container focus:ring-primary-container"
          />
          <span>
            I agree to the InfinityPay{" "}
            <Link href="/terms" target="_blank" className="font-semibold text-primary-container hover:underline">
              Terms of Service
            </Link>
          </span>
        </label>
        {state?.errors?.agreedToTerms?.map((msg) => (
          <p key={msg} className={errorClass}>
            {msg}
          </p>
        ))}

        <label className="flex items-start gap-3 text-sm text-on-surface">
          <input
            type="checkbox"
            name="agreedToPrivacy"
            className="mt-0.5 h-4 w-4 rounded border-outline-variant text-primary-container focus:ring-primary-container"
          />
          <span>
            I agree to the InfinityPay{" "}
            <Link href="/privacy" target="_blank" className="font-semibold text-primary-container hover:underline">
              Privacy Policy
            </Link>
          </span>
        </label>
        {state?.errors?.agreedToPrivacy?.map((msg) => (
          <p key={msg} className={errorClass}>
            {msg}
          </p>
        ))}

        <label className="flex items-start gap-3 text-sm text-on-surface">
          <input
            type="checkbox"
            name="confirmedAccurate"
            className="mt-0.5 h-4 w-4 rounded border-outline-variant text-primary-container focus:ring-primary-container"
          />
          <span>I confirm that the information provided is accurate</span>
        </label>
        {state?.errors?.confirmedAccurate?.map((msg) => (
          <p key={msg} className={errorClass}>
            {msg}
          </p>
        ))}
      </section>

      <button
        type="submit"
        disabled={pending}
        className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
      >
        {pending ? "Submitting…" : "Submit for Verification"}
      </button>
    </form>
  );
}
