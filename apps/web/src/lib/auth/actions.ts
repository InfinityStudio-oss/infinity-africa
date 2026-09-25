"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";


import { createClient } from "@/lib/supabase/server";
import { getOnboardingStatus, submitMerchantSignup, OnboardingApiError } from "@/lib/onboarding/api";

import type { FormState } from "./form-state";
import { isValidNida } from "./nida";
import { isEmail, validatePassword } from "./password";
import { findByEmail, verifyPassword } from "./mock-store";
import { setMockSession } from "./mock-session";
import { mockAuthEnabled } from "./mock-auth-enabled";
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

  const nidaNumber = get("nidaNumber");
  const password = String(formData.get("password") ?? "");
  const confirmPassword = String(formData.get("confirmPassword") ?? "");

  const businessName = get("businessName");
  const ownerName = get("ownerName");
  const businessCategory = get("businessCategory");
  const businessEmail = get("businessEmail");
  const businessPhone = get("businessPhone");
  const tinNumber = get("tinNumber");
  const websiteOrAppLink = get("websiteOrAppLink");

  const agreedToTerms = formData.get("agreedToTerms") === "on";
  const agreedToPrivacy = formData.get("agreedToPrivacy") === "on";
  const confirmedAccurate = formData.get("confirmedAccurate") === "on";

  const values: Record<string, string> = {
    businessName,
    ownerName,
    businessCategory,
    businessEmail,
    businessPhone,
    tinNumber,
    websiteOrAppLink,
  };

  const errors: Record<string, string[]> = {};

  if (!nidaNumber) errors.nidaNumber = ["NIDA number is required."];
  else if (!isValidNida(nidaNumber)) errors.nidaNumber = ["Enter a valid NIDA number — it should be 20 digits."];

  const passwordErrors = validatePassword(password);
  if (passwordErrors.length > 0) errors.password = passwordErrors;
  if (!confirmPassword) errors.confirmPassword = ["Please confirm your password."];
  else if (confirmPassword !== password) errors.confirmPassword = ["Passwords do not match."];

  if (!businessName) errors.businessName = ["Business name is required."];
  if (!ownerName) errors.ownerName = ["Your name is required."];
  if (!businessCategory) errors.businessCategory = ["Business type is required."];
  if (!businessEmail) errors.businessEmail = ["Email address is required."];
  else if (!isEmail(businessEmail)) errors.businessEmail = ["Enter a valid email address."];
  if (!businessPhone) errors.businessPhone = ["Business phone is required."];

  if (!agreedToTerms) errors.agreedToTerms = ["You must agree to the Terms of Service."];
  if (!agreedToPrivacy) errors.agreedToPrivacy = ["You must agree to the Privacy Policy."];
  if (!confirmedAccurate) errors.confirmedAccurate = ["Please confirm the information provided is accurate."];

  if (Object.keys(errors).length > 0) {
    return { errors, values };
  }

  let result;
  try {
    result = await submitMerchantSignup({
      // The Account owner section was removed from the form: the business
      // email IS the login email, and the business phone the contact phone.
      // "Your Name" carries the person signing up, so it feeds full_name
      // (the auth user's user_metadata.full_name and the submission's
      // contact name) — it is not a second business name.
      full_name: ownerName,
      email: businessEmail,
      password,
      contact_phone: businessPhone,
      nida_number: nidaNumber,
      business_name: businessName,
      business_category: businessCategory,
      // Required (NOT NULL) by the backend but not asked for separately on
      // this form — the business type answers the same question, so it is
      // reused rather than asking twice. The Notes field that used to feed
      // this was removed from signup.
      nature_of_business: businessCategory,
      business_email: businessEmail,
      business_phone: businessPhone,
      tin_number: tinNumber || null,
      website_url: websiteOrAppLink || null,
      accepted_terms: agreedToTerms,
      accepted_privacy: agreedToPrivacy,
    });
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
    // The resend-verification form reads this to know where to resend, so
    // it has to be the address the account was actually created with.
    values: { email: businessEmail },
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

  if (!usedSupabase && !mockAuthEnabled()) {
    // A Supabase outage in production is an outage, not a reason to
    // authenticate someone by weaker means.
    return {
      errors: {},
      formError: "We couldn't reach the sign-in service. Please try again in a moment.",
      values: { email },
    };
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
