"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { ServiceNeeded } from "@infinity/shared";

import { createClient } from "@/lib/supabase/server";
import { getOnboardingStatus, submitMerchantSignup, OnboardingApiError } from "@/lib/onboarding/api";

import type { FormState } from "./form-state";
import { isValidNida } from "./nida";
import { isEmail, validatePassword } from "./password";
import { findByEmail, verifyPassword } from "./mock-store";
import { setMockSession } from "./mock-session";
import { isKnownAuthRejection, isSupabaseConfigured } from "./supabase-status";

/**
 * True when a Supabase Auth sign-in was rejected specifically because the
 * account's email is not confirmed yet — as opposed to a genuinely wrong
 * password. supabase-js reports this as `code: "email_not_confirmed"` (and
 * message "Email not confirmed") on a 400. Kept separate so login can show
 * an accurate "verify your email" message instead of the misleading
 * "Incorrect email or password."
 */
function isEmailNotConfirmed(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const code = "code" in error ? String((error as { code?: unknown }).code ?? "") : "";
  const message = "message" in error ? String((error as { message?: unknown }).message ?? "") : "";
  return code === "email_not_confirmed" || /email not confirmed/i.test(message);
}

/**
 * Absolute URL Supabase should send the merchant back to after they click
 * the confirmation link in their email. Must be an allow-listed redirect
 * URL in the Supabase dashboard (Auth > URL Configuration) — see
 * docs/supabase-auth-settings.md. Prefers the explicit NEXT_PUBLIC_SITE_URL
 * (set to https://infinitypay.me in production) and falls back to the
 * request's own forwarded host so local dev works with no extra config.
 */
async function authCallbackUrl(next: string): Promise<string> {
  let base = process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/+$/, "");
  if (!base) {
    const h = await headers();
    const host = h.get("x-forwarded-host") ?? h.get("host");
    const proto = h.get("x-forwarded-proto") ?? "https";
    base = host ? `${proto}://${host}` : "http://localhost:3000";
  }
  return `${base}/auth/callback?next=${encodeURIComponent(next)}`;
}

/**
 * Re-send the sign-up confirmation email. Always returns the same generic
 * confirmation regardless of whether the address actually needs
 * verification (or exists at all) — account-enumeration protection, same
 * as the forgot-password flow.
 */
export async function resendVerificationAction(_prevState: FormState, formData: FormData): Promise<FormState> {
  const email = String(formData.get("email") ?? "").trim();

  if (!email || !isEmail(email)) {
    return {
      errors: {},
      formError: "Enter the email address you signed up with to resend the verification link.",
      values: { email },
      awaitingEmailVerification: true,
    };
  }

  if (isSupabaseConfigured()) {
    try {
      const supabase = await createClient();
      await supabase.auth.resend({
        type: "signup",
        email,
        options: { emailRedirectTo: await authCallbackUrl("/onboarding") },
      });
    } catch {
      // Swallow — still show the generic confirmation below so a
      // connectivity blip or an unknown address is indistinguishable.
    }
  }

  return {
    errors: {},
    values: { email },
    awaitingEmailVerification: true,
    notice: "If that account still needs verification, we've sent a fresh link. Check your inbox and spam folder.",
  };
}

const VALID_SERVICES = new Set<string>(Object.values(ServiceNeeded));

const SIGNUP_SUCCESS_VERIFY =
  "Account created. Please verify your email, then wait for InfinityPay approval.";
const SIGNUP_SUCCESS_NO_VERIFY =
  "Account created. Your business details have been submitted for review. InfinityPay will contact you if " +
  "additional KYC documents are needed.";

/**
 * Combined merchant signup — account credentials AND business details on
 * one page. Posts to the unauthenticated backend endpoint
 * POST /v1/onboarding/signup, which creates the Supabase Auth user
 * itself (service_role) plus the merchant + PENDING_VERIFICATION
 * onboarding submission, notifies the CEO, and emails a verification
 * link. No merchant is ever auto-approved; no welcome/approval email is
 * sent here.
 */
export async function signupWithBusinessAction(_prevState: FormState, formData: FormData): Promise<FormState> {
  const get = (k: string) => String(formData.get(k) ?? "").trim();

  const fullName = get("fullName");
  const email = get("email");
  const phone = get("phone");
  const nidaNumber = get("nidaNumber");
  const password = String(formData.get("password") ?? "");
  const confirmPassword = String(formData.get("confirmPassword") ?? "");

  const businessName = get("businessName");
  const businessCategory = get("businessCategory");
  const natureOfBusiness = get("natureOfBusiness");
  const physicalAddress = get("physicalAddress");
  const regionCity = get("regionCity");
  const websiteOrAppLink = get("websiteOrAppLink");

  const tinCertRaw = formData.get("tinCertificate");
  const tinCertificate = tinCertRaw instanceof File && tinCertRaw.size > 0 && tinCertRaw.name ? tinCertRaw : null;
  const ALLOWED_DOC_TYPES = new Set(["application/pdf", "image/jpeg", "image/png"]);

  const servicesNeeded = formData
    .getAll("servicesNeeded")
    .map((v) => String(v))
    .filter((v): v is ServiceNeeded => VALID_SERVICES.has(v));

  const agreedToTerms = formData.get("agreedToTerms") === "on";
  const agreedToPrivacy = formData.get("agreedToPrivacy") === "on";
  const confirmedAccurate = formData.get("confirmedAccurate") === "on";

  const values: Record<string, string> = {
    fullName,
    email,
    phone,
    businessName,
    businessCategory,
    natureOfBusiness,
    physicalAddress,
    regionCity,
    websiteOrAppLink,
  };

  const errors: Record<string, string[]> = {};
  if (!fullName) errors.fullName = ["Your name is required."];
  if (!email) errors.email = ["Email address is required."];
  else if (!isEmail(email)) errors.email = ["Enter a valid email address."];
  if (!phone) errors.phone = ["Phone number is required."];

  if (!nidaNumber) errors.nidaNumber = ["NIDA number is required."];
  else if (!isValidNida(nidaNumber)) errors.nidaNumber = ["Enter a valid NIDA number — it should be 20 digits."];

  const passwordErrors = validatePassword(password);
  if (passwordErrors.length > 0) errors.password = passwordErrors;
  if (!confirmPassword) errors.confirmPassword = ["Please confirm your password."];
  else if (confirmPassword !== password) errors.confirmPassword = ["Passwords do not match."];

  if (!businessName) errors.businessName = ["Business name is required."];
  if (!businessCategory) errors.businessCategory = ["Business category is required."];
  if (!natureOfBusiness) errors.natureOfBusiness = ["Nature of business is required."];
  if (!physicalAddress) errors.physicalAddress = ["Physical address is required."];
  if (!regionCity) errors.regionCity = ["Region/city is required."];
  if (servicesNeeded.length === 0) errors.servicesNeeded = ["Select at least one service you need."];

  if (tinCertificate && !ALLOWED_DOC_TYPES.has(tinCertificate.type)) {
    errors.tinCertificate = ["TIN certificate must be a PDF, JPG, or PNG file."];
  }

  if (!agreedToTerms) errors.agreedToTerms = ["You must agree to the Terms of Service."];
  if (!agreedToPrivacy) errors.agreedToPrivacy = ["You must agree to the Privacy Policy."];
  if (!confirmedAccurate) errors.confirmedAccurate = ["Please confirm the information provided is accurate."];

  if (Object.keys(errors).length > 0) {
    return { errors, values };
  }

  let result;
  try {
    result = await submitMerchantSignup(
      {
        full_name: fullName,
        email,
        password,
        contact_phone: phone,
        nida_number: nidaNumber,
        business_name: businessName,
        business_category: businessCategory,
        nature_of_business: natureOfBusiness,
        physical_address: physicalAddress,
        region_city: regionCity,
        website_url: websiteOrAppLink || null,
        services_needed: servicesNeeded,
        accepted_terms: agreedToTerms,
        accepted_privacy: agreedToPrivacy,
      },
      tinCertificate,
    );
  } catch (err) {
    if (err instanceof OnboardingApiError) {
      if (err.code === "nida_required" || err.code === "nida_invalid") {
        return { errors: { nidaNumber: [err.message] }, values };
      }
      if (err.code === "conflict") {
        return { errors: { email: ["An account with this email already exists."] }, values };
      }
      return { errors: {}, formError: err.message, values };
    }
    return {
      errors: {},
      formError: "Couldn't reach InfinityPay. Check your connection and try again.",
      values,
    };
  }

  return {
    errors: {},
    values: { email },
    awaitingEmailVerification: result.email_confirmation_required,
    notice: result.email_confirmation_required ? SIGNUP_SUCCESS_VERIFY : SIGNUP_SUCCESS_NO_VERIFY,
  };
}

export async function loginAction(_prevState: FormState, formData: FormData): Promise<FormState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");

  const errors: Record<string, string[]> = {};
  if (!email) errors.email = ["Email address is required."];
  if (!password) errors.password = ["Password is required."];

  if (Object.keys(errors).length > 0) {
    return { errors, values: { email } };
  }

  let userId: string | null = null;
  let usedSupabase = false;
  let isPlatformAdmin = false;
  let accessToken: string | null = null;

  if (isSupabaseConfigured()) {
    try {
      const supabase = await createClient();
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
      usedSupabase = true;
      userId = data.user?.id ?? null;
      accessToken = data.session?.access_token ?? null;

      if (userId) {
        const { data: adminRow } = await supabase
          .from("platform_admins")
          .select("id")
          .eq("user_id", userId)
          .maybeSingle();
        isPlatformAdmin = Boolean(adminRow);
      }
    } catch (err) {
      if (isEmailNotConfirmed(err)) {
        return {
          errors: {},
          formError:
            "Please verify your email before logging in. Check your inbox for the verification link.",
          values: { email },
          awaitingEmailVerification: true,
        };
      }
      if (isKnownAuthRejection(err)) {
        return { errors: {}, formError: "Incorrect email or password.", values: { email } };
      }
      // Connectivity failure — fall through to the mock store below.
    }
  }

  if (!usedSupabase) {
    const mockUser = findByEmail(email);
    if (!mockUser || !verifyPassword(mockUser, password)) {
      return { errors: {}, formError: "Incorrect email or password.", values: { email } };
    }
    await setMockSession(mockUser.id);
    userId = mockUser.id;
  }

  if (!userId) {
    return { errors: {}, formError: "Incorrect email or password.", values: { email } };
  }

  if (isPlatformAdmin) {
    redirect("/admin");
  }

  const onboarding = accessToken ? await getOnboardingStatus(accessToken) : null;
  redirect(onboarding?.next_path ?? "/onboarding");
}
