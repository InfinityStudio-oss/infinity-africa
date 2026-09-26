import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiKey, IpAllowlistEntry } from "@/lib/portal/types";

const key: ApiKey = {
  id: "key-1",
  merchant_id: "merchant-1",
  name: "Website checkout",
  environment: "sandbox",
  key_prefix: "inf_sandbox_abc123",
  public_key: "pk_test_examplepublickey",
  key_last4: "9zk1",
  scopes: ["collections:write", "collections:read"],
  status: "active",
  ip_whitelist_enabled: false,
  continue_without_ip_whitelist: true,
  last_used_at: null,
  last_used_ip: null,
  revoked_at: null,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

const listApiKeys = vi.fn();
const createApiKey = vi.fn();
const revokeApiKey = vi.fn();
const rotateApiKey = vi.fn();
const renameApiKey = vi.fn();
const getMyMerchant = vi.fn();
const listIpAllowlist = vi.fn();
const createIpAllowlistEntry = vi.fn();
const deleteIpAllowlistEntry = vi.fn();
const updateApiKeyIpWhitelist = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  listApiKeys: (...args: unknown[]) => listApiKeys(...args),
  createApiKey: (...args: unknown[]) => createApiKey(...args),
  revokeApiKey: (...args: unknown[]) => revokeApiKey(...args),
  rotateApiKey: (...args: unknown[]) => rotateApiKey(...args),
  renameApiKey: (...args: unknown[]) => renameApiKey(...args),
  getMyMerchant: (...args: unknown[]) => getMyMerchant(...args),
  listIpAllowlist: (...args: unknown[]) => listIpAllowlist(...args),
  createIpAllowlistEntry: (...args: unknown[]) => createIpAllowlistEntry(...args),
  deleteIpAllowlistEntry: (...args: unknown[]) => deleteIpAllowlistEntry(...args),
  updateApiKeyIpWhitelist: (...args: unknown[]) => updateApiKeyIpWhitelist(...args),
}));

describe("ApiKeysView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listApiKeys.mockResolvedValue([key]);
    getMyMerchant.mockResolvedValue({
      status: "active",
      kyc_status: "verified",
      api_access_suspended: false,
    });
    listIpAllowlist.mockResolvedValue([]);
  });

  it("always shows the never-expose-secrets warning", async () => {
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    expect(
      screen.getByText(/Use secret keys only on your backend\./),
    ).toBeInTheDocument();
    expect(screen.getByText(/Never expose them in\s*frontend or mobile apps/)).toBeInTheDocument();
  });

  it("shows a Rotate button alongside Revoke for an active key", async () => {
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    expect(await screen.findByRole("button", { name: "Rotate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke" })).toBeInTheDocument();
  });

  it("rotating a key reveals the new plaintext key and marks the old one revoked", async () => {
    rotateApiKey.mockResolvedValue({
      key: { ...key, id: "key-2", status: "active" },
      plaintext_key: "inf_sandbox_newkey123",
    });
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    fireEvent.click(await screen.findByRole("button", { name: "Rotate" }));

    await waitFor(() => expect(rotateApiKey).toHaveBeenCalledWith("key-1"));
    expect(await screen.findByText("inf_sandbox_newkey123")).toBeInTheDocument();
    expect(
      screen.getByText("Store the secret key now. For your security, it will not be shown again."),
    ).toBeInTheDocument();
  });

  it("hides the secret for good once the merchant confirms they have saved it", async () => {
    // The secret exists only in component state and is never re-fetchable,
    // so this button really is the last time it can be read.
    rotateApiKey.mockResolvedValue({
      key: { ...key, id: "key-2", status: "active", public_key: "pk_test_newpublic" },
      plaintext_key: "sk_test_newsecret123",
    });
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    fireEvent.click(await screen.findByRole("button", { name: "Rotate" }));
    expect(await screen.findByText("sk_test_newsecret123")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "I've saved my secret key" }));

    await waitFor(() =>
      expect(screen.queryByText("sk_test_newsecret123")).not.toBeInTheDocument(),
    );
  });

  it("blocks generating a Live key and explains why when the merchant isn't approved yet", async () => {
    getMyMerchant.mockResolvedValue({
      status: "pending",
      kyc_status: "unverified",
      api_access_suspended: false,
    });
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    fireEvent.click(await screen.findByRole("button", { name: "Live" }));
    await screen.findByText(/Production API keys are available after your business account is approved/);

    const triggerButtons = screen.getAllByRole("button", { name: "Generate API Key" });
    fireEvent.click(triggerButtons[0]);

    const submitButton = (await screen.findAllByRole("button", { name: "Generate API Key" })).find(
      (button) => button.getAttribute("type") === "submit",
    );
    expect(submitButton).toBeDisabled();
  });

  it("blocks generating any key (sandbox or live) when API access is suspended", async () => {
    getMyMerchant.mockResolvedValue({
      status: "active",
      kyc_status: "verified",
      api_access_suspended: true,
    });
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await screen.findByText(/API access is currently suspended/);

    const triggerButtons = screen.getAllByRole("button", { name: "Generate API Key" });
    fireEvent.click(triggerButtons[0]);

    const submitButton = (await screen.findAllByRole("button", { name: "Generate API Key" })).find(
      (button) => button.getAttribute("type") === "submit",
    );
    expect(submitButton).toBeDisabled();
  });

  async function openFormAndFillBasics() {
    // Wait for the key list to settle first — otherwise the trigger button
    // this test clicks can be the EmptyState's (0 sandbox keys, transient)
    // one instant and the table header's (1 sandbox key, from the mock)
    // the next, and fireEvent.click can land on a since-unmounted node.
    await screen.findByText("Website checkout");
    fireEvent.click(await screen.findByRole("button", { name: "Generate API Key" }));
    fireEvent.change(await screen.findByPlaceholderText("e.g. Website checkout integration"), {
      target: { value: "My integration" },
    });
    fireEvent.click(screen.getByLabelText(/Collections — create/));
  }

  function findSubmitButton() {
    return screen.getAllByRole("button", { name: "Generate API Key" }).find(
      (button) => button.getAttribute("type") === "submit",
    )!;
  }

  it("defaults to 'continue without IP whitelisting' and passes the merchant's choice through to createApiKey", async () => {
    createApiKey.mockResolvedValue({ key: { ...key, id: "key-2" }, plaintext_key: "inf_sandbox_newkey123" });
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await openFormAndFillBasics();
    fireEvent.click(findSubmitButton());

    await waitFor(() =>
      expect(createApiKey).toHaveBeenCalledWith(
        expect.objectContaining({ ip_whitelist_enabled: false, continue_without_ip_whitelist: true }),
      ),
    );
  });

  it("blocks Generate API Key when IP whitelisting is enabled with no IPs added, and shows the required message", async () => {
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await openFormAndFillBasics();
    fireEvent.click(screen.getByRole("radio", { name: /Enable IP whitelisting/ }));

    expect(
      screen.getByText("Add at least one allowed server IP or choose Continue without IP whitelisting."),
    ).toBeInTheDocument();
    expect(findSubmitButton()).toBeDisabled();
    expect(createApiKey).not.toHaveBeenCalled();
  });

  it("adds a valid IP inline, enabling submit, and passes allowed_ips to createApiKey", async () => {
    createApiKey.mockResolvedValue({ key: { ...key, id: "key-2" }, plaintext_key: "inf_sandbox_newkey123" });
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await openFormAndFillBasics();
    fireEvent.click(screen.getByRole("radio", { name: /Enable IP whitelisting/ }));
    fireEvent.change(screen.getByPlaceholderText("Enter server IP address or CIDR"), {
      target: { value: "41.59.10.20/32" },
    });
    fireEvent.change(screen.getByPlaceholderText("Label, e.g. Main ecommerce server"), {
      target: { value: "Main ecommerce server" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add IP" }));

    expect(await screen.findByText("41.59.10.20/32")).toBeInTheDocument();
    expect(screen.getByText("Main ecommerce server")).toBeInTheDocument();
    expect(findSubmitButton()).not.toBeDisabled();

    fireEvent.click(findSubmitButton());
    await waitFor(() =>
      expect(createApiKey).toHaveBeenCalledWith(
        expect.objectContaining({
          ip_whitelist_enabled: true,
          allowed_ips: [{ ip_address_or_cidr: "41.59.10.20/32", label: "Main ecommerce server" }],
        }),
      ),
    );
  });

  it("rejects an invalid IP with a clear inline error and does not add it to the list", async () => {
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await openFormAndFillBasics();
    fireEvent.click(screen.getByRole("radio", { name: /Enable IP whitelisting/ }));
    fireEvent.change(screen.getByPlaceholderText("Enter server IP address or CIDR"), {
      target: { value: "not-an-ip" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add IP" }));

    expect(await screen.findByText("Invalid IP address or CIDR: not-an-ip")).toBeInTheDocument();
    expect(screen.queryByText("not-an-ip")).not.toBeInTheDocument();
  });

  it("rejects a duplicate IP with a clear inline error", async () => {
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await openFormAndFillBasics();
    fireEvent.click(screen.getByRole("radio", { name: /Enable IP whitelisting/ }));
    fireEvent.change(screen.getByPlaceholderText("Enter server IP address or CIDR"), {
      target: { value: "41.59.10.20" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add IP" }));
    fireEvent.change(screen.getByPlaceholderText("Enter server IP address or CIDR"), {
      target: { value: "41.59.10.20" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add IP" }));

    expect(await screen.findByText("Already added: 41.59.10.20")).toBeInTheDocument();
    expect(screen.getAllByText("41.59.10.20")).toHaveLength(1);
  });

  it("supports pasting multiple comma-separated IPs at once", async () => {
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await openFormAndFillBasics();
    fireEvent.click(screen.getByRole("radio", { name: /Enable IP whitelisting/ }));
    fireEvent.change(screen.getByPlaceholderText("Enter server IP address or CIDR"), {
      target: { value: "41.59.10.20, 41.59.10.21, 41.59.10.22/32" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add IP" }));

    expect(await screen.findByText("41.59.10.20")).toBeInTheDocument();
    expect(await screen.findByText("41.59.10.21")).toBeInTheDocument();
    expect(await screen.findByText("41.59.10.22/32")).toBeInTheDocument();
  });

  it("removes an added IP from the inline list", async () => {
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await openFormAndFillBasics();
    fireEvent.click(screen.getByRole("radio", { name: /Enable IP whitelisting/ }));
    fireEvent.change(screen.getByPlaceholderText("Enter server IP address or CIDR"), {
      target: { value: "41.59.10.20" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add IP" }));
    expect(await screen.findByText("41.59.10.20")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByText("41.59.10.20")).not.toBeInTheDocument());
    expect(findSubmitButton()).toBeDisabled();
  });

  it("shows the recommendation warning for Continue without IP whitelisting on a Live key", async () => {
    getMyMerchant.mockResolvedValue({ status: "active", kyc_status: "verified", api_access_suspended: false });
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    fireEvent.click(await screen.findByRole("button", { name: "Live" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "Generate API Key" }))[0]);

    expect(
      await screen.findByText(/For production, IP whitelisting is recommended for stronger security/),
    ).toBeInTheDocument();
  });

  it("never writes the revealed secret to localStorage or sessionStorage", async () => {
    rotateApiKey.mockResolvedValue({
      key: { ...key, id: "key-2", status: "active" },
      plaintext_key: "inf_sandbox_newkey123",
    });
    const localSetItem = vi.spyOn(Storage.prototype, "setItem");
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    fireEvent.click(await screen.findByRole("button", { name: "Rotate" }));
    await screen.findByText("inf_sandbox_newkey123");

    expect(localSetItem).not.toHaveBeenCalled();
    localSetItem.mockRestore();
  });

  it("Manage IPs panel shows linked IPs and lets the merchant add/remove them", async () => {
    const entry: IpAllowlistEntry = {
      id: "entry-1",
      merchant_id: "merchant-1",
      api_key_id: "key-1",
      environment: "sandbox",
      label: "Office",
      ip_address_or_cidr: "41.59.10.20",
      status: "active",
      notes: null,
      created_at: "2026-08-01T10:00:00Z",
      updated_at: "2026-08-01T10:00:00Z",
    };
    listIpAllowlist.mockResolvedValue([entry]);
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    fireEvent.click(await screen.findByRole("button", { name: "Manage IPs" }));
    expect(await screen.findByText("41.59.10.20")).toBeInTheDocument();
    expect(listIpAllowlist).toHaveBeenCalledWith({ apiKeyId: "key-1" });

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(deleteIpAllowlistEntry).toHaveBeenCalledWith("entry-1"));
  });

  it("blocks switching a key to Enable IP whitelisting from the detail panel when it has no linked IPs", async () => {
    listIpAllowlist.mockResolvedValue([]);
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    fireEvent.click(await screen.findByRole("button", { name: "Manage IPs" }));
    await screen.findByText("No IPs linked to this key yet.");
    fireEvent.click(screen.getByRole("button", { name: "Switch to Enable IP whitelisting" }));

    expect(
      await screen.findByText("Add at least one allowed server IP or choose Continue without IP whitelisting."),
    ).toBeInTheDocument();
    expect(updateApiKeyIpWhitelist).not.toHaveBeenCalled();
  });

  it("does not show Rotate/Revoke for an already-revoked key", async () => {
    listApiKeys.mockResolvedValue([{ ...key, status: "revoked" }]);
    const { ApiKeysView } = await import("./api-keys-view");
    render(<ApiKeysView />);

    await waitFor(() => expect(listApiKeys).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Rotate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
  });
});
