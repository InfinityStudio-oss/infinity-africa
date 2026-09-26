import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AdminApiKeyPlatformRow } from "@/lib/admin/types";

vi.mock("@/lib/admin/live-actions", () => ({
  revokeAdminApiKeyAction: vi.fn(),
}));

function row(overrides: Partial<AdminApiKeyPlatformRow>): AdminApiKeyPlatformRow {
  return {
    id: "key-1",
    merchant_id: "merchant-1",
    merchant_name: "Amani Traders",
    merchant_code: "27048391",
    name: "Production key",
    environment: "live",
    // Deliberately the legacy `inf_` format: 11 such keys exist in
    // production and must keep rendering. New keys are sk_/pk_ pairs.
    key_prefix: "inf_live_abc123",
    key_last4: "9zk1",
    scopes: ["collections:write"],
    status: "active",
    ip_whitelist_enabled: false,
    last_used_at: "2026-08-24T10:00:00Z",
    last_used_ip: null,
    revoked_at: null,
    created_at: "2026-08-01T10:00:00Z",
    ...overrides,
  };
}

describe("ApiKeysTable", () => {
  it("shows every real column for an active key, including a Revoke action", async () => {
    const { ApiKeysTable } = await import("./api-keys-table");
    render(<ApiKeysTable rows={[row({})]} />);

    expect(screen.getByText("Amani Traders")).toBeInTheDocument();
    expect(screen.getByText("Production key")).toBeInTheDocument();
    expect(screen.getByText(/inf_live_abc123/)).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByTitle("Revoke")).toBeInTheDocument();
  });

  it("hides the Revoke action for an already-revoked key", async () => {
    const { ApiKeysTable } = await import("./api-keys-table");
    render(<ApiKeysTable rows={[row({ status: "revoked", revoked_at: "2026-08-20T00:00:00Z" })]} />);

    expect(screen.getByText("Revoked")).toBeInTheDocument();
    expect(screen.queryByTitle("Revoke")).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no keys", async () => {
    const { ApiKeysTable } = await import("./api-keys-table");
    render(<ApiKeysTable rows={[]} />);

    expect(screen.getByText("No API keys have been issued yet.")).toBeInTheDocument();
  });
});
