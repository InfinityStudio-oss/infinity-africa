import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/portal/api", () => ({
  listApiKeys: vi.fn().mockResolvedValue([]),
  getMyMerchant: vi.fn().mockResolvedValue(null),
  getWebhookConfig: vi.fn().mockResolvedValue({ webhook_url: null, subscribed_events: null, has_secret: false, last_delivery: null }),
  listIpAllowlist: vi.fn().mockResolvedValue([]),
  listApiLogs: vi.fn().mockResolvedValue([]),
}));

describe("ApiCredentialsPage", () => {
  it("renders the API Credentials content directly, without wrapping it in its own PortalShell", async () => {
    // app/portal/layout.tsx already wraps every /portal/* page in exactly
    // one PortalShell (sidebar, topbar, auth check, <main>) — this page
    // used to also render its own PortalShell, double-nesting the whole
    // shell and producing a large, unexplained left gap in production.
    // This page component must not import PortalShell or render a <main>
    // of its own ever again.
    const { default: ApiCredentialsPage } = await import("./page");
    const { container } = render(<ApiCredentialsPage />);

    expect(await screen.findByText("API Credentials")).toBeInTheDocument();
    expect(container.querySelectorAll("main")).toHaveLength(0);
    expect(container.querySelector(".portal-shell-scope")).toBeNull();
  });

  it("sets the page title via metadata, not a rendered heading override", async () => {
    const pageModule = await import("./page");
    expect(pageModule.metadata.title).toBe("API Credentials | InfinityPay");
  });
});
