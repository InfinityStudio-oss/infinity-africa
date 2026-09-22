import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (...args: unknown[]) => redirect(...args),
}));

describe("old API-related routes redirect into the unified API Credentials page", () => {
  it("/dashboard/api-keys -> /portal/api-credentials?tab=keys", async () => {
    redirect.mockClear();
    const { default: MerchantApiKeysRedirect } = await import("@/app/dashboard/api-keys/page");
    MerchantApiKeysRedirect();
    expect(redirect).toHaveBeenCalledWith("/portal/api-credentials?tab=keys");
  });

  it("/portal/api-keys -> /portal/api-credentials?tab=keys", async () => {
    redirect.mockClear();
    const { default: PortalApiKeysRedirect } = await import("@/app/portal/api-keys/page");
    PortalApiKeysRedirect();
    expect(redirect).toHaveBeenCalledWith("/portal/api-credentials?tab=keys");
  });

  it("/dashboard/developer-docs -> /portal/api-credentials?tab=docs", async () => {
    redirect.mockClear();
    const { default: MerchantDeveloperDocsRedirect } = await import("@/app/dashboard/developer-docs/page");
    MerchantDeveloperDocsRedirect();
    expect(redirect).toHaveBeenCalledWith("/portal/api-credentials?tab=docs");
  });

  it("/portal/developer-docs -> /portal/api-credentials?tab=docs", async () => {
    redirect.mockClear();
    const { default: PortalDeveloperDocsRedirect } = await import("@/app/portal/developer-docs/page");
    PortalDeveloperDocsRedirect();
    expect(redirect).toHaveBeenCalledWith("/portal/api-credentials?tab=docs");
  });

  it("/portal/webhooks -> /portal/api-credentials?tab=webhooks", async () => {
    redirect.mockClear();
    const { default: PortalWebhooksRedirect } = await import("@/app/portal/webhooks/page");
    PortalWebhooksRedirect();
    expect(redirect).toHaveBeenCalledWith("/portal/api-credentials?tab=webhooks");
  });

  it("/portal/ip-allowlist -> /portal/api-credentials?tab=ip-allowlist", async () => {
    redirect.mockClear();
    const { default: PortalIpAllowlistRedirect } = await import("@/app/portal/ip-allowlist/page");
    PortalIpAllowlistRedirect();
    expect(redirect).toHaveBeenCalledWith("/portal/api-credentials?tab=ip-allowlist");
  });

  it("/portal/api-logs -> /portal/api-credentials?tab=logs", async () => {
    redirect.mockClear();
    const { default: PortalApiLogsRedirect } = await import("@/app/portal/api-logs/page");
    PortalApiLogsRedirect();
    expect(redirect).toHaveBeenCalledWith("/portal/api-credentials?tab=logs");
  });
});
