import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard/overview",
}));

describe("Sidebar", () => {
  it("does not show an Upgrade Plan CTA", async () => {
    const { Sidebar } = await import("./sidebar");
    const { container } = render(<Sidebar open onClose={() => {}} />);

    expect(screen.queryByText(/Upgrade Plan/i)).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Upgrade Plan/i);
  });

  it("shows a Team nav item linking to /dashboard/users", async () => {
    const { Sidebar } = await import("./sidebar");
    render(<Sidebar open onClose={() => {}} />);

    expect(screen.getByRole("link", { name: /Team/i })).toHaveAttribute("href", "/dashboard/users");
  });

  it("shows a single API Credentials nav item linking to /portal/api-credentials", async () => {
    const { Sidebar } = await import("./sidebar");
    render(<Sidebar open onClose={() => {}} />);

    expect(screen.getByRole("link", { name: /API Credentials/i })).toHaveAttribute(
      "href",
      "/portal/api-credentials",
    );
  });

  it("no longer shows API Keys, Developer Docs, Webhooks, IP Allowlist, or API Logs as separate nav items", async () => {
    const { Sidebar } = await import("./sidebar");
    render(<Sidebar open onClose={() => {}} />);

    for (const label of ["API Keys", "Developer Docs", "Webhooks", "IP Allowlist", "API Logs"]) {
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
  });
});
