/**
 * Data-access boundary for the super admin dashboard's remaining MOCK
 * resources — customers, pricing, API keys, reconciliation, settlement
 * accounts, compliance/KYC, provider status, support tickets. (Admin team
 * moved to live-api.ts on 2026-10-01 — it was showing three invented
 * people on a live platform.)
 * These still live at /admin/* (out of scope for the /super-admin/* live
 * rewire — see lib/admin/live-api.ts for the 10 resources that moved and
 * are now real). No "server-only" marker here: 5 of these pages are still
 * "use client" and import from this file directly.
 */

import {
  mockAdminCustomers,
  mockComplianceFlags,
  mockDuplicateReferences,
  mockFailedCallbacks,
  mockIncidents,
  mockKycQueue,
  mockPlatformApiKeys,
  mockProviderCallbackLogs,
  mockProviderHealth,
  mockSettlementAccounts,
  mockSupportTickets,
  mockUnmatchedTransactions,
} from "./mock-data";
import type {
  AdminCustomerRow,
  ComplianceFlagRow,
  DuplicateReferenceRow,
  FailedCallbackRow,
  IncidentRow,
  KycReviewRow,
  PlatformApiKeyRow,
  ProviderCallbackLogRow,
  ProviderHealth,
  SettlementAccountRow,
  SupportTicketRow,
  UnmatchedTransactionRow,
} from "./types";

const store = {
  customers: mockAdminCustomers(),
  apiKeys: mockPlatformApiKeys(),
  failedCallbacks: mockFailedCallbacks(),
  unmatchedTransactions: mockUnmatchedTransactions(),
  duplicateReferences: mockDuplicateReferences(),
  callbackLogs: mockProviderCallbackLogs(),
  settlementAccounts: mockSettlementAccounts(),
  kycQueue: mockKycQueue(),
  complianceFlags: mockComplianceFlags(),
  providerHealth: mockProviderHealth(),
  incidents: mockIncidents(),
  supportTickets: mockSupportTickets(),
};

/** Audit Logs is now a real, live page (lib/admin/live-api.ts) — nothing
 * reads this anymore, but the 4 mutations below still append to it so
 * their behavior is unchanged rather than silently dropping a side effect. */
interface MockAuditEntry {
  id: string;
  timestamp: string;
  admin_name: string;
  action: string;
  target: string;
  ip_address: string;
}

let _mockAuditTrail: MockAuditEntry[] = [];

function nowIso(): string {
  return new Date().toISOString();
}

function appendAuditLog(action: string, target: string) {
  _mockAuditTrail = [
    { id: `log-${Date.now()}`, timestamp: nowIso(), admin_name: "Admin User", action, target, ip_address: "127.0.0.1" },
    ..._mockAuditTrail,
  ];
}

// --- Customers -----------------------------------------------------------

export async function listAdminCustomers(): Promise<AdminCustomerRow[]> {
  return store.customers;
}

// --- API Keys ------------------------------------------------------------

export async function listPlatformApiKeys(): Promise<PlatformApiKeyRow[]> {
  return store.apiKeys;
}

export async function revokeApiKey(keyId: string): Promise<void> {
  const key = store.apiKeys.find((k) => k.id === keyId);
  if (!key) return;
  key.status = "Revoked";
  appendAuditLog("API Key Revoked", `API Key: ${key.merchant_name} — ${key.key_masked}`);
}

// --- Reconciliation ----------------------------------------------------

export async function listFailedCallbacks(): Promise<FailedCallbackRow[]> {
  return store.failedCallbacks;
}

export async function listUnmatchedTransactions(): Promise<UnmatchedTransactionRow[]> {
  return store.unmatchedTransactions;
}

export async function listDuplicateReferences(): Promise<DuplicateReferenceRow[]> {
  return store.duplicateReferences;
}

export async function listProviderCallbackLogs(): Promise<ProviderCallbackLogRow[]> {
  return store.callbackLogs;
}

export async function retryFailedCallback(callbackId: string): Promise<void> {
  store.failedCallbacks = store.failedCallbacks.filter((row) => row.id !== callbackId);
}

// --- Settlement accounts -------------------------------------------------

export async function listSettlementAccounts(): Promise<SettlementAccountRow[]> {
  return store.settlementAccounts;
}

// --- Compliance / KYC --------------------------------------------------

export async function listKycQueue(): Promise<KycReviewRow[]> {
  return store.kycQueue;
}

export async function listComplianceFlags(): Promise<ComplianceFlagRow[]> {
  return store.complianceFlags;
}

export async function approveKyc(reviewId: string): Promise<void> {
  const review = store.kycQueue.find((row) => row.id === reviewId);
  if (!review) return;
  store.kycQueue = store.kycQueue.filter((row) => row.id !== reviewId);
  appendAuditLog("Merchant Approved", `Merchant: ${review.merchant_name}`);
}

export async function rejectKyc(reviewId: string): Promise<void> {
  const review = store.kycQueue.find((row) => row.id === reviewId);
  if (!review) return;
  store.kycQueue = store.kycQueue.filter((row) => row.id !== reviewId);
  appendAuditLog("Merchant Rejected", `Merchant: ${review.merchant_name}`);
}

// --- Provider status -------------------------------------------------------

export async function listProviderHealth(): Promise<ProviderHealth[]> {
  return store.providerHealth;
}

export async function listIncidents(): Promise<IncidentRow[]> {
  return store.incidents;
}

// --- Support tickets ---------------------------------------------------

export async function listSupportTickets(): Promise<SupportTicketRow[]> {
  return store.supportTickets;
}

// --- Admin team --------------------------------------------------------
