"use server";

import { redirect } from "next/navigation";

import { ServiceNeeded } from "@infinity/shared";

import { getCurrentUser } from "@/lib/auth/current-user";
import type { FormState } from "@/lib/auth/form-state";
import { isValidNida } from "@/lib/auth/nida";

import { OnboardingApiError, submitOnboardingAccount } from "./api";

const VALID_SERVICES = new Set<string>(Object.values(ServiceNeeded));

export async function submitOnboardingAction(_prevState: FormState, formData: FormData): Promise<FormState> {
  const user = await getCurrentUser();
  if (!user) {
    redirect("/merchant/login");
  }

  const businessName = String(formData.get("businessName") ?? "").trim();
  const natureOfBusiness = String(formData.get("natureOfBusiness") ?? "").trim();
  const businessCategory = String(formData.get("businessCategory") ?? "").trim();
  const physicalAddress = String(formData.get("physicalAddress") ?? "").trim();
  const regionCity = String(formData.get("regionCity") ?? "").trim();
  const contactPhone = String(formData.get("contactPhone") ?? "").trim();
  const nidaNumber = String(formData.get("nidaNumber") ?? "").trim();
  const websiteOrAppLink = String(formData.get("websiteOrAppLink") ?? "").trim();

  const servicesNeeded = formData
    .getAll("servicesNeeded")
    .map((v) => String(v))
    .filter((v): v is ServiceNeeded => VALID_SERVICES.has(v));

  const agreedToTerms = formData.get("agreedToTerms") === "on";
  const agreedToPrivacy = formData.get("agreedToPrivacy") === "on";
  const confirmedAccurate = formData.get("confirmedAccurate") === "on";

  const errors: Record<string, string[]> = {};
  if (!businessName) errors.businessName = ["Business name is required."];
  if (!natureOfBusiness) errors.natureOfBusiness = ["Nature of business is required."];
  if (!businessCategory) errors.businessCategory = ["Business category is required."];
  if (!physicalAddress) errors.physicalAddress = ["Physical address is required."];
  if (!regionCity) errors.regionCity = ["Region/city is required."];
  if (!contactPhone) errors.contactPhone = ["Contact phone number is required."];
  if (!nidaNumber) errors.nidaNumber = ["NIDA number is required."];
  else if (!isValidNida(nidaNumber)) errors.nidaNumber = ["Enter a valid NIDA number — it should be 20 digits."];
  if (servicesNeeded.length === 0) errors.servicesNeeded = ["Select at least one service you need."];

  if (!agreedToTerms) errors.agreedToTerms = ["You must agree to the InfinityPay Terms of Service."];
  if (!agreedToPrivacy) errors.agreedToPrivacy = ["You must agree to the InfinityPay Privacy Policy."];
  if (!confirmedAccurate) errors.confirmedAccurate = ["You must confirm the information provided is accurate."];

  const values = {
    businessName,
    natureOfBusiness,
    businessCategory,
    physicalAddress,
    regionCity,
    contactPhone,
    nidaNumber,
    websiteOrAppLink,
  };

  if (Object.keys(errors).length > 0) {
    return { errors, values };
  }

  try {
    await submitOnboardingAccount({
      business_name: businessName,
      nature_of_business: natureOfBusiness,
      business_category: businessCategory,
      physical_address: physicalAddress,
      region_city: regionCity,
      website_url: websiteOrAppLink || null,
      contact_phone: contactPhone,
      nida_number: nidaNumber,
      services_needed: servicesNeeded,
      accepted_terms: agreedToTerms,
      accepted_privacy: agreedToPrivacy,
    });
  } catch (err) {
    if (err instanceof OnboardingApiError && (err.code === "nida_required" || err.code === "nida_invalid")) {
      return { errors: { nidaNumber: [err.message] }, values };
    }
    const formError =
      err instanceof OnboardingApiError
        ? err.code === "conflict"
          ? "You already have a merchant account submitted for review."
          : err.message
        : "Couldn't reach InfinityPay. Check your connection and try again.";
    return { errors: {}, formError, values };
  }

  redirect("/merchant/overview");
}
