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

  // --- pages an unverified merchant cannot reach ---------------------------
  //
  // Pay by Link, Withdrawals and Invoices call requireVerifiedMerchant()
  // and redirect a pending merchant back to Overview. Rendering them as
  // ordinary links meant a click produced a blank flash and a silent
  // bounce, which reads as the portal being broken rather than the
  // account not being approved yet.

  const LOCKED = ["Pay by Link", "Withdrawals", "Invoices"];

  it.each(LOCKED)("offers no link to %s while the account is unverified", async (label) => {
    const { Sidebar } = await import("./sidebar");
    render(<Sidebar open onClose={() => {}} verified={false} />);

    expect(screen.queryByRole("link", { name: new RegExp(label, "i") })).not.toBeInTheDocument();
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("says why those items are unavailable", async () => {
    const { Sidebar } = await import("./sidebar");
    render(<Sidebar open onClose={() => {}} verified={false} />);

    expect(screen.getByText("Withdrawals").closest("div")).toHaveAttribute(
      "title",
      "Available once your account is verified",
    );
  });

  it("still links the pages a pending merchant can actually use", async () => {
    // Wallet, Collections and Transactions have no verification guard —
    // locking them would invent a restriction the backend does not have.
    const { Sidebar } = await import("./sidebar");
    render(<Sidebar open onClose={() => {}} verified={false} />);

    for (const label of ["Wallet", "Collections", "Transactions", "Overview"]) {
      expect(screen.getByRole("link", { name: new RegExp(label, "i") })).toBeInTheDocument();
    }
  });

  it("links everything once the account is verified", async () => {
    const { Sidebar } = await import("./sidebar");
    render(<Sidebar open onClose={() => {}} verified />);

    for (const label of LOCKED) {
      expect(screen.getByRole("link", { name: new RegExp(label, "i") })).toBeInTheDocument();
    }
  });

  it("defaults to verified, so a caller that does not know locks nothing", async () => {
    const { Sidebar } = await import("./sidebar");
    render(<Sidebar open onClose={() => {}} />);

    expect(screen.getByRole("link", { name: /Withdrawals/i })).toBeInTheDocument();
  });
});
