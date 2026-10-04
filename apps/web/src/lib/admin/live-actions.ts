"use server";

import { revalidatePath } from "next/cache";

import {
  activateCollectionPricingRule,
  addRiskAlertNote,
  approveDocumentRequest,
  approveIpAllowlistEntry,
  approveMerchantOnboarding,
  approveWithdrawal,
  createMerchantCollectionPricingRule,
  createMerchantPricingRule,
  createPlatformFallbackCollectionPricingRule,
  createPlatformFallbackPricingRule,
  deactivateCollectionPricingRule,
  deactivatePricingRule,
  reconcilePendingWithdrawals,
  refreshWithdrawalStatus,
  retryWithdrawalPayout,
  reinstateMerchantApiAccess,
  rejectDocumentRequest,
  rejectIpAllowlistEntry,
  rejectWithdrawal,
  requestDocumentsForAlert,
  requestInfoWithdrawal,
  requestRefundForDispute,
  revokeAdminApiKey,
  suspendMerchantApiAccess,
  updateAdminMerchantNotificationSettings,
  updateCollectionPricingRule,
  updateDisputeStatus,
  updateMerchantStatus,
  updatePricingRule,
  updateRefundStatus,
  updateRiskAlertStatus,
  type CollectionPricingRuleInput,
  type PricingRuleInput,
} from "./live-api";
import type { MerchantAccountStatus } from "./types";

export async function approveMerchantAction(merchantId: string) {
  await approveMerchantOnboarding(merchantId);
  revalidatePath("/super-admin/merchants");
}

export async function setMerchantStatusAction(merchantId: string, status: MerchantAccountStatus) {
  await updateMerchantStatus(merchantId, status);
  revalidatePath("/super-admin/merchants");
}

export async function revokeAdminApiKeyAction(apiKeyId: string) {
  await revokeAdminApiKey(apiKeyId);
  revalidatePath("/super-admin/api-keys");
}

export async function suspendMerchantApiAccessAction(merchantId: string) {
  await suspendMerchantApiAccess(merchantId);
  revalidatePath(`/super-admin/merchants/${merchantId}`);
}

export async function reinstateMerchantApiAccessAction(merchantId: string) {
  await reinstateMerchantApiAccess(merchantId);
  revalidatePath(`/super-admin/merchants/${merchantId}`);
}

export async function approveIpAllowlistEntryAction(entryId: string, merchantId: string) {
  await approveIpAllowlistEntry(entryId);
  revalidatePath(`/super-admin/merchants/${merchantId}`);
}

export async function rejectIpAllowlistEntryAction(entryId: string, merchantId: string) {
  await rejectIpAllowlistEntry(entryId);
  revalidatePath(`/super-admin/merchants/${merchantId}`);
}

export interface WithdrawalActionState {
  error: string | null;
  /** true once a submit completed successfully — drives the inline
   * confirmation in withdrawals-table.tsx. */
  ok: boolean;
  /** Optional success detail, e.g. the reconcile summary. */
  message: string | null;
}

/** Same silent-failure fix as runPricingRuleAction / runRiskAlertAction
 * (reported: "Reconcile Pending button is not working"). Every action in
 * the Withdrawal Approval Queue was a bare `<form action>` — a successful
 * Approve/Reject just revalidated with no confirmation, and a failed
 * request (an API 5xx, a stale-status 409, …) threw straight out with
 * nothing shown, so on an approval screen you couldn't tell whether the
 * money moved. Threading state through useActionState fixes both. */
async function runWithdrawalAction(run: () => Promise<string | void>): Promise<WithdrawalActionState> {
  let message: string | void;
  try {
    message = await run();
  } catch (err) {
    return { error: err instanceof Error ? err.message : "Something went wrong. Try again.", ok: false, message: null };
  }
  revalidatePath("/super-admin/withdrawals");
  return { error: null, ok: true, message: message ?? null };
}

// The approve/refresh/reconcile actions don't read the form body, so they
// omit the (prevState, formData) params useActionState would pass — a
// shorter function is still assignable to the longer callback type.
export async function approveWithdrawalAction(withdrawalId: string): Promise<WithdrawalActionState> {
  return runWithdrawalAction(async () => {
    await approveWithdrawal(withdrawalId);
    return "Approved — sent to the provider.";
  });
}

export async function rejectWithdrawalAction(
  withdrawalId: string,
  _prevState: WithdrawalActionState | null,
  formData: FormData,
): Promise<WithdrawalActionState> {
  const rejectionReason = String(formData.get("rejection_reason") ?? "").trim();
  if (!rejectionReason) return { error: "Enter a reason for rejecting this withdrawal.", ok: false, message: null };
  return runWithdrawalAction(async () => {
    await rejectWithdrawal(withdrawalId, rejectionReason);
    return "Withdrawal rejected.";
  });
}

export async function requestInfoWithdrawalAction(
  withdrawalId: string,
  _prevState: WithdrawalActionState | null,
  formData: FormData,
): Promise<WithdrawalActionState> {
  const message = String(formData.get("message") ?? "").trim();
  if (!message) return { error: "Enter what you need from the merchant.", ok: false, message: null };
  const requestedDocuments = String(formData.get("requested_documents") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return runWithdrawalAction(async () => {
    await requestInfoWithdrawal(withdrawalId, { message, requestedDocuments });
    return "Information requested from the merchant.";
  });
}

export async function refreshWithdrawalStatusAction(withdrawalId: string): Promise<WithdrawalActionState> {
  return runWithdrawalAction(async () => {
    await refreshWithdrawalStatus(withdrawalId);
    return "Status refreshed.";
  });
}

export async function retryWithdrawalPayoutAction(withdrawalId: string): Promise<WithdrawalActionState> {
  return runWithdrawalAction(async () => {
    await retryWithdrawalPayout(withdrawalId);
    return "Retried — sent to the provider again.";
  });
}

export async function reconcilePendingWithdrawalsAction(): Promise<WithdrawalActionState> {
  return runWithdrawalAction(async () => {
    const summary = await reconcilePendingWithdrawals();
    return `Checked ${summary.checked} · resolved ${summary.resolved} · still pending ${summary.still_pending}.`;
  });
}

// --- Risk monitoring ---------------------------------------------------------

export interface RiskAlertActionState {
  error: string | null;
  /** true once a submit has completed successfully — drives the inline
   * "Updated" confirmation in risk-monitoring-table.tsx. A "use server"
   * module can only export async functions, so the matching idle value
   * ({ error: null, ok: false }) is declared in that component, not here. */
  ok: boolean;
}

/** Same silent-failure fix as runPricingRuleAction above (reported:
 * "Update Status button is not responsive"). These forms were bare
 * `<form action={fn.bind(...)}>` — on success they showed nothing, and a
 * failed request (non-2xx from the API) threw straight out of the action
 * with no error boundary, so the form just sat there. Threading state
 * through useActionState gives the admin a pending state, an "Updated"
 * confirmation, and a visible error. */
async function runRiskAlertAction(
  run: () => Promise<unknown>,
  ...extraPaths: string[]
): Promise<RiskAlertActionState> {
  try {
    await run();
  } catch (err) {
    return { error: err instanceof Error ? err.message : "Something went wrong. Try again.", ok: false };
  }
  revalidatePath("/super-admin/risk-monitoring");
  for (const path of extraPaths) revalidatePath(path);
  return { error: null, ok: true };
}

export async function updateRiskAlertStatusAction(
  alertId: string,
  _prevState: RiskAlertActionState | null,
  formData: FormData,
): Promise<RiskAlertActionState> {
  const status = String(formData.get("status") ?? "");
  if (!status) return { error: "Pick a status first.", ok: false };
  return runRiskAlertAction(() => updateRiskAlertStatus(alertId, status));
}

export async function addRiskAlertNoteAction(
  alertId: string,
  _prevState: RiskAlertActionState | null,
  formData: FormData,
): Promise<RiskAlertActionState> {
  const note = String(formData.get("note") ?? "").trim();
  if (!note) return { error: "Enter a note first.", ok: false };
  return runRiskAlertAction(() => addRiskAlertNote(alertId, note));
}

export async function requestDocumentsForAlertAction(
  alertId: string,
  _prevState: RiskAlertActionState | null,
  formData: FormData,
): Promise<RiskAlertActionState> {
  const requestedDocuments = String(formData.get("requested_documents") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const reason = String(formData.get("reason") ?? "").trim();
  if (requestedDocuments.length === 0 || !reason) {
    return { error: "Enter at least one document and a reason.", ok: false };
  }
  return runRiskAlertAction(
    () => requestDocumentsForAlert(alertId, { requested_documents: requestedDocuments, reason }),
    "/super-admin/document-requests",
  );
}

// --- Document requests -------------------------------------------------------

export async function approveDocumentRequestAction(requestId: string) {
  await approveDocumentRequest(requestId);
  revalidatePath("/super-admin/document-requests");
}

export async function rejectDocumentRequestAction(requestId: string) {
  await rejectDocumentRequest(requestId);
  revalidatePath("/super-admin/document-requests");
}

// --- Disputes ------------------------------------------------------------------

export async function updateDisputeStatusAction(disputeId: string, formData: FormData) {
  const status = String(formData.get("status") ?? "");
  if (!status) return;
  const note = String(formData.get("note") ?? "").trim() || undefined;
  await updateDisputeStatus(disputeId, status, note);
  revalidatePath("/super-admin/disputes");
}

export async function requestRefundForDisputeAction(disputeId: string, formData: FormData) {
  const amount = String(formData.get("amount") ?? "").trim();
  if (!amount) return;
  await requestRefundForDispute(disputeId, amount);
  revalidatePath("/super-admin/disputes");
}

export async function updateRefundStatusAction(disputeId: string, formData: FormData) {
  const status = String(formData.get("status") ?? "");
  if (!status) return;
  await updateRefundStatus(disputeId, status);
  revalidatePath("/super-admin/disputes");
}

// --- Pricing rules -------------------------------------------------------------

function pricingRuleInputFromFormData(formData: FormData): PricingRuleInput {
  const get = (key: string) => {
    const value = String(formData.get(key) ?? "").trim();
    return value ? value : undefined;
  };
  return {
    channel: get("channel") ?? null,
    destination_code: get("destination_code") ?? null,
    percentage_fee: get("percentage_fee") ?? "0",
    flat_fee: get("flat_fee") ?? "0",
    minimum_fee: get("minimum_fee") ?? null,
    maximum_fee: get("maximum_fee") ?? null,
    processor_fee_flat: get("processor_fee_flat") ?? "0",
    processor_fee_pass_through: formData.get("processor_fee_pass_through") === "on",
    effective_from: get("effective_from") ?? null,
    effective_to: get("effective_to") ?? null,
    label: get("label") ?? null,
  };
}

export interface PricingRuleActionState {
  error: string | null;
}

/** A failed create/save previously threw straight out of the form
 * action with nothing to show for it — apiWrite's error still reaches
 * the browser console, but the form itself just sits there looking like
 * the button did nothing (reported: "Save Changes is not clickable").
 * Catching here and returning the message via useActionState (see
 * pricing-rules-view.tsx's RuleEditForm/RuleCreateForm) makes a real
 * failure (a validation rule like maximum_fee < minimum_fee, a network
 * error, ...) visible instead of silent. */
async function runPricingRuleAction(run: () => Promise<unknown>): Promise<PricingRuleActionState> {
  try {
    await run();
  } catch (err) {
    return { error: err instanceof Error ? err.message : "Couldn't save this pricing rule. Try again." };
  }
  revalidatePath("/super-admin/pricing-rules");
  return { error: null };
}

export async function createMerchantPricingRuleAction(
  merchantId: string,
  _prevState: PricingRuleActionState | null,
  formData: FormData,
): Promise<PricingRuleActionState> {
  return runPricingRuleAction(() => createMerchantPricingRule(merchantId, pricingRuleInputFromFormData(formData)));
}

export async function createPlatformFallbackPricingRuleAction(
  _prevState: PricingRuleActionState | null,
  formData: FormData,
): Promise<PricingRuleActionState> {
  return runPricingRuleAction(() => createPlatformFallbackPricingRule(pricingRuleInputFromFormData(formData)));
}

export async function updatePricingRuleAction(
  ruleId: string,
  _prevState: PricingRuleActionState | null,
  formData: FormData,
): Promise<PricingRuleActionState> {
  return runPricingRuleAction(() => updatePricingRule(ruleId, pricingRuleInputFromFormData(formData)));
}

export async function deactivatePricingRuleAction(ruleId: string) {
  await deactivatePricingRule(ruleId);
  revalidatePath("/super-admin/pricing-rules");
}

// --- Collection pricing rules ---------------------------------------------------

function collectionPricingRuleInputFromFormData(formData: FormData): CollectionPricingRuleInput {
  const get = (key: string) => {
    const value = String(formData.get(key) ?? "").trim();
    return value ? value : undefined;
  };
  return {
    channel: get("channel") ?? null,
    percentage_fee: get("percentage_fee") ?? "0",
    // flat_fee/minimum_fee/maximum_fee have no input in RuleFields
    // anymore (collection-pricing-rules-view.tsx) — left as `undefined`
    // (not defaulted to "0"/null) so JSON.stringify drops them from the
    // request body entirely. On create, the backend's own Pydantic
    // defaults apply (flat_fee=0, min/max=null); on update, PATCH's
    // exclude_unset=True then leaves whatever a rule already has
    // untouched, rather than silently resetting it to 0/null on every
    // edit through this simplified form.
    flat_fee: get("flat_fee"),
    minimum_fee: get("minimum_fee"),
    maximum_fee: get("maximum_fee"),
    effective_from: get("effective_from") ?? null,
    effective_to: get("effective_to") ?? null,
    label: get("label") ?? null,
    notes: get("notes") ?? null,
  };
}

export type CollectionPricingRuleActionState = PricingRuleActionState;

async function runCollectionPricingRuleAction(run: () => Promise<unknown>): Promise<CollectionPricingRuleActionState> {
  try {
    await run();
  } catch (err) {
    return { error: err instanceof Error ? err.message : "Couldn't save this collection pricing rule. Try again." };
  }
  revalidatePath("/super-admin/pricing-rules");
  return { error: null };
}

export async function createMerchantCollectionPricingRuleAction(
  merchantId: string,
  _prevState: CollectionPricingRuleActionState | null,
  formData: FormData,
): Promise<CollectionPricingRuleActionState> {
  return runCollectionPricingRuleAction(() =>
    createMerchantCollectionPricingRule(merchantId, collectionPricingRuleInputFromFormData(formData)),
  );
}

export async function createPlatformFallbackCollectionPricingRuleAction(
  _prevState: CollectionPricingRuleActionState | null,
  formData: FormData,
): Promise<CollectionPricingRuleActionState> {
  return runCollectionPricingRuleAction(() =>
    createPlatformFallbackCollectionPricingRule(collectionPricingRuleInputFromFormData(formData)),
  );
}

export async function updateCollectionPricingRuleAction(
  ruleId: string,
  _prevState: CollectionPricingRuleActionState | null,
  formData: FormData,
): Promise<CollectionPricingRuleActionState> {
  return runCollectionPricingRuleAction(() =>
    updateCollectionPricingRule(ruleId, collectionPricingRuleInputFromFormData(formData)),
  );
}

export async function deactivateCollectionPricingRuleAction(ruleId: string) {
  await deactivateCollectionPricingRule(ruleId);
  revalidatePath("/super-admin/pricing-rules");
}

export async function activateCollectionPricingRuleAction(ruleId: string) {
  await activateCollectionPricingRule(ruleId);
  revalidatePath("/super-admin/pricing-rules");
}

// --- Notification settings (Super Admin editing a merchant's own) --------------

export type NotificationSettingsActionState = PricingRuleActionState;

export async function updateAdminMerchantNotificationSettingsAction(
  merchantId: string,
  _prevState: NotificationSettingsActionState | null,
  formData: FormData,
): Promise<NotificationSettingsActionState> {
  const get = (key: string) => {
    const value = String(formData.get(key) ?? "").trim();
    return value ? value : null;
  };
  try {
    await updateAdminMerchantNotificationSettings(merchantId, {
      primary_notification_email: get("primary_notification_email"),
      secondary_notification_email: get("secondary_notification_email"),
      collection_notifications_enabled: formData.get("collection_notifications_enabled") === "on",
    });
  } catch (err) {
    return { error: err instanceof Error ? err.message : "Couldn't save notification settings. Try again." };
  }
  revalidatePath(`/super-admin/merchants/${merchantId}`);
  return { error: null };
}
