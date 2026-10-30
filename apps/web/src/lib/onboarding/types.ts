/**
 * Types for the real /v1/onboarding/* and /v1/admin/onboarding/* API
 * responses — see apps/api/app/schemas/onboarding.py, which this file
 * mirrors field-for-field. Enums (AccountStatus, ServiceNeeded,
 * DocumentType, DocumentUploadStatus) live in @infinity/shared, shared with
 * the backend's app/schemas/enums.py.
 */

import type { AccountStatus, DocumentType, DocumentUploadStatus, ServiceNeeded } from "@infinity/shared";

export interface OnboardingMerchantAccountInput {
  business_name: string;
  nature_of_business: string;
  business_category: string;
  // Dropped from the Get Started form; the older two-step /onboarding
  // form still sends them, so they stay accepted, just optional.
  physical_address?: string;
  region_city?: string;
  website_url: string | null;
  contact_phone: string;
  nida_number: string;
  tin_number?: string | null;
  legal_business_name?: string | null;
  business_email?: string | null;
  business_phone?: string | null;
  notes?: string | null;
  services_needed?: ServiceNeeded[];
  accepted_terms: boolean;
  accepted_privacy: boolean;
}

/** Combined signup: account credentials + business details in one call to
 * POST /v1/onboarding/signup (unauthenticated — the backend creates the
 * Supabase Auth user itself). */
export interface MerchantSignupInput extends OnboardingMerchantAccountInput {
  full_name: string;
  email: string;
  password: string;
  /** Invite code, from /create-account?ref=CODE. Optional: the backend
   * records an unusable one and carries on, so a bad code can never be
   * the reason a business fails to sign up. */
  referral_code?: string;
}

export interface MerchantSignupResult {
  merchant_id: string;
  merchant_code: string | null;
  account_status: AccountStatus;
  email_confirmation_required: boolean;
}

export interface OnboardingMerchant {
  id: string;
  merchant_code: string | null;
  business_name: string;
  legal_name: string | null;
  country: string;
  currency: string;
  contact_email: string;
  contact_phone: string | null;
  status: string;
  kyc_status: string;
  webhook_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface OnboardingMerchantAccountResult {
  merchant: OnboardingMerchant;
  account_status: AccountStatus;
  next_path: string;
}

export interface OnboardingStatus {
  has_account: boolean;
  onboarding_completed: boolean;
  merchant_id: string | null;
  account_status: AccountStatus | null;
  /** merchants.status — "pending" | "active" | "suspended" | "closed".
   * Not the same thing as `account_status`, which is the onboarding
   * submission's review status: a business approved long ago and
   * suspended yesterday is still APPROVED there. Login reads this one. */
  merchant_status: string | null;
  next_path: string;
}

export interface OnboardingDocument {
  id: string;
  merchant_id: string;
  document_type: DocumentType;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  upload_status: DocumentUploadStatus;
  uploaded_at: string;
  signed_url: string | null;
}

/** Super-admin list/detail view — joins the merchant's own profile fields
 * onto its onboarding_submissions row. */
export interface RelatedBusiness {
  merchant_id: string;
  business_name: string;
  merchant_code: string | null;
  status: string | null;
}

export interface OnboardingSubmission {
  id: string;
  merchant_id: string;
  merchant_code: string | null;
  business_name: string;
  legal_name: string | null;
  owner_email: string;
  contact_phone: string | null;
  nature_of_business: string;
  business_category: string;
  physical_address: string;
  region_city: string;
  website_url: string | null;
  notes: string | null;
  /** Masked — last 4 digits of the NIDA only. The full number is never
   * returned by the API. Null for pre-NIDA submissions. */
  nida_last4: string | null;
  /** Other businesses already held by this same owner — matched on the
   * same identity keys signup uses (NIDA, then phone). Empty for almost
   * every application. Informational only: one owner may legitimately
   * run several businesses, and nothing is refused because of this. */
  other_businesses: RelatedBusiness[];
  tin_number: string | null;
  expected_monthly_volume: string | null;
  services_needed: ServiceNeeded[];
  review_status: AccountStatus;
  review_note: string | null;
  document_status: DocumentUploadStatus;
  submitted_at: string;
  updated_at: string;
  documents: OnboardingDocument[];
  // Set only in the response to an approve action, and only when the
  // merchant's welcome email couldn't be sent because their email is
  // missing — see app/schemas/onboarding.py::OnboardingSubmissionResponse.
  welcome_email_warning?: string | null;
}
