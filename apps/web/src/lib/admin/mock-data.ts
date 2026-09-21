/** Seed data for the super admin dashboard's remaining mock resources
 * (customers, pricing, API keys, reconciliation, settlement accounts,
 * compliance/KYC, provider status, support tickets, admin team) — the 10
 * live resources' mock generators were removed when those pages moved to
 * /super-admin/* and lib/admin/live-api.ts. See lib/admin/api.ts for how
 * this is consumed — no page/component should import this file directly. */

import type {
  AdminCustomerRow,
  AdminTeamMember,
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

let seq = 2000;
function id(prefix: string): string {
  seq += 1;
  return `${prefix}-${seq}`;
}

export function mockAdminCustomers(): AdminCustomerRow[] {
  const rows: Array<[string, string, string[], string, string, AdminCustomerRow["status"]]> = [
    ["Asha Mrisho", "+255712345678", ["Juma Traders Ltd", "Amani Store"], "842000.00", "2026-08-13T00:00:00Z", "active"],
    ["Peter Kimaro", "+255754112233", ["Neema Salon"], "128500.00", "2026-08-10T00:00:00Z", "active"],
    ["Grace Mushi", "+255765998112", ["Baraka Textiles", "Kilimanjaro Cafe"], "1204300.00", "2026-06-28T00:00:00Z", "inactive"],
    ["Fatuma Ally", "+255682445990", ["Baraka Textiles"], "610000.00", "2026-08-12T00:00:00Z", "active"],
    ["John Mrema", "+255719223456", ["Kilimanjaro Cafe"], "54200.00", "2026-08-11T00:00:00Z", "active"],
    ["Rehema Juma", "+255786331087", ["Grace Mwakalinga Designs"], "305000.00", "2026-08-11T00:00:00Z", "active"],
    ["Michael Nyerere", "+255745667209", ["Juma Traders Ltd"], "1842750.00", "2026-03-03T00:00:00Z", "inactive"],
  ];
  return rows.map(([name, phone, merchants, total_spent, last_transaction_at, status]) => ({
    id: id("cus"),
    name,
    phone,
    merchants,
    total_spent,
    last_transaction_at,
    status,
  }));
}

export function mockPlatformApiKeys(): PlatformApiKeyRow[] {
  const rows: Array<[string, string, PlatformApiKeyRow["environment"], string, PlatformApiKeyRow["status"]]> = [
    ["Juma Traders Ltd", "sk_live_••••••3F2A", "Live", "2026-08-13T09:12:00Z", "Active"],
    ["Amani Store", "sk_test_••••••9K1B", "Sandbox", "2026-08-12T16:40:00Z", "Active"],
    ["Neema Salon", "sk_live_••••••7C4D", "Live", "2026-08-13T07:55:00Z", "Active"],
    ["Baraka Textiles", "sk_test_••••••2M8E", "Sandbox", "2026-08-10T14:02:00Z", "Active"],
    ["Kilimanjaro Cafe", "sk_live_••••••5A9F", "Live", "2026-08-02T11:20:00Z", "Revoked"],
    ["Grace Mwakalinga Designs", "sk_test_••••••0Q3H", "Sandbox", "2026-08-13T08:30:00Z", "Active"],
  ];
  return rows.map(([merchant_name, key_masked, environment, last_used_at, status]) => ({
    id: id("key"),
    merchant_name,
    key_masked,
    environment,
    last_used_at,
    status,
  }));
}

export function mockFailedCallbacks(): FailedCallbackRow[] {
  return [
    { id: id("cbk"), provider: "Selcom Pesa", event_type: "payout.completed", reference: "SEL-99213X", received_at: "2026-08-13T10:12:00Z", error: "Timeout — 504 Gateway Timeout" },
    { id: id("cbk"), provider: "M-Pesa", event_type: "collection.confirmed", reference: "MPESA-QK4821", received_at: "2026-08-13T08:47:00Z", error: "Invalid signature" },
    { id: id("cbk"), provider: "CRDB Bank", event_type: "transfer.failed", reference: "CRDB-77102B", received_at: "2026-08-12T22:03:00Z", error: "Account number mismatch" },
  ];
}

export function mockUnmatchedTransactions(): UnmatchedTransactionRow[] {
  return [
    { id: id("umx"), reference: "TIGO-40218Q", provider: "Tigo Pesa", amount: "32000.00", received_at: "2026-08-13T06:55:00Z" },
    { id: id("umx"), reference: "AIRTEL-88231", provider: "Airtel Money", amount: "15500.00", received_at: "2026-08-12T19:41:00Z" },
  ];
}

export function mockDuplicateReferences(): DuplicateReferenceRow[] {
  return [
    { id: id("dup"), reference: "SEL-31029A", occurrences: 3, first_seen: "2026-08-11T14:02:00Z", last_seen: "2026-08-11T14:09:00Z" },
    { id: id("dup"), reference: "MPESA-11827", occurrences: 2, first_seen: "2026-08-09T09:15:00Z", last_seen: "2026-08-09T09:16:00Z" },
  ];
}

export function mockProviderCallbackLogs(): ProviderCallbackLogRow[] {
  const rows: Array<[string, string, string, string, number, ProviderCallbackLogRow["match_status"]]> = [
    ["2026-08-13T14:02:11Z", "Selcom Pesa", "payout.completed", "SEL-77401C", 200, "Matched"],
    ["2026-08-13T10:12:03Z", "Selcom Pesa", "payout.completed", "SEL-99213X", 504, "Failed"],
    ["2026-08-13T06:55:44Z", "Tigo Pesa", "collection.confirmed", "TIGO-40218Q", 200, "Unmatched"],
    ["2026-08-11T14:09:02Z", "Selcom Pesa", "collection.confirmed", "SEL-31029A", 200, "Duplicate"],
    ["2026-08-10T17:23:19Z", "M-Pesa", "payout.completed", "MPESA-55019", 200, "Matched"],
  ];
  return rows.map(([timestamp, provider, event, reference, http_status, match_status]) => ({
    id: id("cbl"),
    timestamp,
    provider,
    event,
    reference,
    http_status,
    match_status,
  }));
}

export function mockSettlementAccounts(): SettlementAccountRow[] {
  const rows: Array<[string, string, string, string, SettlementAccountRow["status"]]> = [
    ["Selcom Pesa", "SEL-••••-8821", "41250000.00", "2026-08-13T09:15:00Z", "Active"],
    ["M-Pesa", "MPS-••••-4407", "38900000.00", "2026-08-13T08:40:00Z", "Active"],
    ["Tigo Pesa", "TGP-••••-2290", "19600000.00", "2026-08-12T22:05:00Z", "Under Review"],
    ["CRDB Bank", "CRDB-••••-5563", "21150000.00", "2026-08-13T07:30:00Z", "Active"],
    ["NMB Bank", "NMB-••••-9034", "7500000.00", "2026-08-13T06:55:00Z", "Active"],
  ];
  return rows.map(([provider, account_reference, balance, last_settled_at, status]) => ({
    id: id("stl"),
    provider,
    account_reference,
    balance,
    last_settled_at,
    status,
  }));
}

export function mockKycQueue(): KycReviewRow[] {
  const rows: Array<[string, string, string]> = [
    ["Juma Traders Ltd", "National ID", "2026-08-10T00:00:00Z"],
    ["Amani Store", "Business License", "2026-08-11T00:00:00Z"],
    ["Neema Salon", "TIN Certificate", "2026-08-12T00:00:00Z"],
    ["Baraka Textiles", "National ID", "2026-08-13T00:00:00Z"],
  ];
  return rows.map(([merchant_name, document_type, submitted_at]) => ({ id: id("kyc"), merchant_name, document_type, submitted_at }));
}

export function mockComplianceFlags(): ComplianceFlagRow[] {
  const rows: Array<[string, string, string, ComplianceFlagRow["risk_level"]]> = [
    ["Kilimanjaro Cafe", "Unusual transaction volume spike", "2026-08-09T00:00:00Z", "High"],
    ["Grace Mwakalinga Designs", "Mismatched business registration details", "2026-08-10T00:00:00Z", "Medium"],
    ["Juma Traders Ltd", "Sanctions list partial match — false positive suspected", "2026-08-11T00:00:00Z", "High"],
  ];
  return rows.map(([merchant_name, reason, flagged_at, risk_level]) => ({ id: id("flg"), merchant_name, reason, flagged_at, risk_level }));
}

export function mockProviderHealth(): ProviderHealth[] {
  return [
    { id: id("prv"), name: "Selcom Pesa", status: "operational", uptime_month: "99.98%", avg_response_ms: 142 },
    { id: id("prv"), name: "M-Pesa", status: "operational", uptime_month: "99.95%", avg_response_ms: 180 },
    { id: id("prv"), name: "Tigo Pesa", status: "degraded", uptime_month: "98.2%", avg_response_ms: 960 },
    { id: id("prv"), name: "Airtel Money", status: "operational", uptime_month: "99.91%", avg_response_ms: 210 },
    { id: id("prv"), name: "HaloPesa", status: "down", uptime_month: "91.4%", avg_response_ms: null },
    { id: id("prv"), name: "CRDB Bank", status: "operational", uptime_month: "99.99%", avg_response_ms: 98 },
    { id: id("prv"), name: "NMB Bank", status: "operational", uptime_month: "99.97%", avg_response_ms: 115 },
  ];
}

export function mockIncidents(): IncidentRow[] {
  const rows: Array<[string, string, string, string, IncidentRow["status"]]> = [
    ["HaloPesa", "Connectivity timeout on collection API", "2026-08-14T06:40:00Z", "Ongoing", "Ongoing"],
    ["Tigo Pesa", "Elevated response times on withdrawal callbacks", "2026-08-13T14:05:00Z", "2h 10m", "Resolved"],
    ["CRDB Bank", "Scheduled maintenance window, settlement delays", "2026-08-09T01:00:00Z", "45m", "Resolved"],
    ["M-Pesa", "Intermittent STK push failures", "2026-08-03T19:20:00Z", "1h 05m", "Resolved"],
  ];
  return rows.map(([provider, incident, start_time, duration, status]) => ({ id: id("inc"), provider, incident, start_time, duration, status }));
}

export function mockSupportTickets(): SupportTicketRow[] {
  const rows: Array<[string, string, string, SupportTicketRow["priority"], SupportTicketRow["status"], string]> = [
    ["TCK-4021", "Juma Traders Ltd", "Payout stuck in processing for 2 days", "Urgent", "Open", "2026-08-14T00:00:00Z"],
    ["TCK-4018", "Amani Store", "Cannot generate payment link for new product", "High", "Awaiting Merchant", "2026-08-13T00:00:00Z"],
    ["TCK-4012", "Neema Salon", "Question about settlement schedule", "Medium", "Resolved", "2026-08-12T00:00:00Z"],
    ["TCK-4005", "Baraka Textiles", "Request to increase daily transaction limit", "Medium", "Open", "2026-08-11T00:00:00Z"],
    ["TCK-3998", "Kilimanjaro Cafe", "Webhook not firing for completed orders", "Urgent", "Awaiting Merchant", "2026-08-10T00:00:00Z"],
    ["TCK-3981", "Grace Mwakalinga Designs", "Clarification on invoice reminder emails", "Low", "Resolved", "2026-08-08T00:00:00Z"],
    ["TCK-3966", "Juma Traders Ltd", "Old API key still showing as active", "Low", "Closed", "2026-08-03T00:00:00Z"],
  ];
  return rows.map(([ticket_number, merchant_name, subject, priority, status, updated_at]) => ({
    id: id("tkt"),
    ticket_number,
    merchant_name,
    subject,
    priority,
    status,
    updated_at,
  }));
}

export function mockAdminTeam(): AdminTeamMember[] {
  return [
    { id: id("adm"), name: "Admin User", email: "admin@infinitypay.me", role: "Super Admin", status: "active" },
    { id: id("adm"), name: "David Komba", email: "david.komba@infinitypay.me", role: "Operations Admin", status: "active" },
    { id: id("adm"), name: "Rehema Ally", email: "rehema.ally@infinitypay.me", role: "Support Admin", status: "active" },
  ];
}
