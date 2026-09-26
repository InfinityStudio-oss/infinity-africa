import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiKey } from "@/lib/portal/types";

const listApiKeys = vi.fn();
const getMyMerchant = vi.fn();
const getWebhookConfig = vi.fn();
const listIpAllowlist = vi.fn();
const listApiLogs = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  listApiKeys: (...args: unknown[]) => listApiKeys(...args),
  getMyMerchant: (...args: unknown[]) => getMyMerchant(...args),
  getWebhookConfig: (...args: unknown[]) => getWebhookConfig(...args),
  listIpAllowlist: (...args: unknown[]) => listIpAllowlist(...args),
  listApiLogs: (...args: unknown[]) => listApiLogs(...args),
}));

const key: ApiKey = {
  id: "key-1",
  merchant_id: "merchant-1",
  name: "Sandbox key",
  environment: "sandbox",
  key_prefix: "inf_sandbox_abc123",
  public_key: "pk_test_examplepublickey",
  key_last4: "9zk1",
  scopes: ["collections:write"],
  status: "active",
  ip_whitelist_enabled: false,
  continue_without_ip_whitelist: true,
  last_used_at: null,
  last_used_ip: null,
  revoked_at: null,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

describe("ApiCredentialsOverview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listApiKeys.mockResolvedValue([]);
    getMyMerchant.mockResolvedValue(null);
    getWebhookConfig.mockResolvedValue({ webhook_url: null, subscribed_events: null, has_secret: false, last_delivery: null });
    listIpAllowlist.mockResolvedValue([]);
    listApiLogs.mockResolvedValue([]);
  });

  it("shows a single status card followed by a plain checklist (no stat-card grid)", async () => {
    const { ApiCredentialsOverview } = await import("./api-credentials-overview");
    render(<ApiCredentialsOverview onSelectTab={vi.fn()} />);

    expect(await screen.findByText("Quick Setup Checklist")).toBeInTheDocument();
    expect(screen.queryByText("Sandbox Keys")).not.toBeInTheDocument();
    expect(screen.queryByText("Production Keys")).not.toBeInTheDocument();
    expect(screen.queryByText("Webhook Status")).not.toBeInTheDocument();
  });

  it("summarizes integration state in a sentence instead of stat cards", async () => {
    listApiKeys.mockResolvedValue([key]);
    const { ApiCredentialsOverview } = await import("./api-credentials-overview");
    render(<ApiCredentialsOverview onSelectTab={vi.fn()} />);

    expect(await screen.findByText(/1 sandbox key/)).toBeInTheDocument();
  });

  it("renders each checklist item as an icon + label + arrow row, matching the main Portal Overview's checklist style", async () => {
    const { ApiCredentialsOverview } = await import("./api-credentials-overview");
    render(<ApiCredentialsOverview onSelectTab={vi.fn()} />);

    const item = await screen.findByText("Create API key");
    const row = item.closest("button");
    expect(row).not.toBeNull();
    expect(row?.querySelector(".material-symbols-outlined")).not.toBeNull();
    // No numbered badge like "1", "2" — just the icon and the arrow.
    expect(row?.textContent).not.toMatch(/^[1-6]/);
  });

  it("clicking a checklist row calls onSelectTab with that section", async () => {
    const onSelectTab = vi.fn();
    const { ApiCredentialsOverview } = await import("./api-credentials-overview");
    render(<ApiCredentialsOverview onSelectTab={onSelectTab} />);

    fireEvent.click(await screen.findByText("Add webhook URL"));
    expect(onSelectTab).toHaveBeenCalledWith("webhooks");
  });

  it("shows the merchant's ID in the page header", async () => {
    getMyMerchant.mockResolvedValue({
      id: "merchant-1",
      merchant_code: "27048391",
      business_name: "Masanja Traders",
      legal_name: null,
      country: "TZ",
      currency: "TZS",
      contact_email: "merchant@example.com",
      contact_phone: null,
      status: "active",
      kyc_status: "verified",
      api_access_suspended: false,
      webhook_url: null,
      created_at: "2026-08-01T10:00:00Z",
      updated_at: "2026-08-01T10:00:00Z",
    });
    const { ApiCredentialsOverview } = await import("./api-credentials-overview");
    render(<ApiCredentialsOverview onSelectTab={vi.fn()} />);

    expect(await screen.findByText("27048391")).toBeInTheDocument();
  });

  it("shows the last API request when one exists", async () => {
    listApiLogs.mockResolvedValue([
      { id: "log-1", api_key_id: "key-1", environment: "sandbox", method: "POST", path: "/v1/collections/wallet-push", status_code: 202, ip_address: "1.2.3.4", duration_ms: 120, created_at: "2026-08-20T09:00:00Z" },
    ]);
    const { ApiCredentialsOverview } = await import("./api-credentials-overview");
    render(<ApiCredentialsOverview onSelectTab={vi.fn()} />);

    expect(await screen.findByText(/POST \/v1\/collections\/wallet-push/)).toBeInTheDocument();
  });
});
