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
