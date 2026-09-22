import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { UserRole } from "@infinity/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MerchantUser } from "@/lib/portal/types";

const membership: MerchantUser = {
  id: "row-1",
  user_id: "user-1",
  merchant_id: "merchant-1",
  full_name: "Amina Admin",
  email: "amina@merchant.co.tz",
  role: UserRole.MERCHANT_ADMIN,
  status: "active",
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

vi.mock("@/lib/portal/api", () => ({
  getMyMembership: vi.fn().mockResolvedValue(membership),
}));

vi.mock("@/lib/supabase/logout", () => ({
  merchantLogout: vi.fn(),
}));

describe("Topbar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the signed-in user's real name, email, and role in the account menu", async () => {
    const { Topbar } = await import("./topbar");
    render(<Topbar onOpenSidebar={() => {}} />);

    fireEvent.click(screen.getByLabelText("Account menu"));

    await waitFor(() => expect(screen.getByText("Amina Admin")).toBeInTheDocument());
    const menu = screen.getByText("Amina Admin").closest("div")!.parentElement as HTMLElement;
    expect(within(menu).getByText("amina@merchant.co.tz")).toBeInTheDocument();
    expect(within(menu).getByText("Merchant Admin")).toBeInTheDocument();
    expect(within(menu).getByRole("button", { name: "Log out" })).toBeInTheDocument();
    expect(within(menu).getByRole("link", { name: /Profile & Settings/i })).toHaveAttribute(
      "href",
      "/dashboard/profile",
    );
  });

  it("does not show a notifications bell", async () => {
    const { Topbar } = await import("./topbar");
    render(<Topbar onOpenSidebar={() => {}} />);

    expect(screen.queryByLabelText("Notifications")).not.toBeInTheDocument();
  });

  it("links New Payment Link to a real route instead of a dead button", async () => {
    const { Topbar } = await import("./topbar");
    render(<Topbar onOpenSidebar={() => {}} />);

    expect(screen.getByRole("link", { name: /New Pay by Link/i })).toHaveAttribute("href", "/dashboard/pay-by-link");
  });

  it("opens a help popover showing the real support email, instead of a silent mailto link", async () => {
    const { Topbar } = await import("./topbar");
    render(<Topbar onOpenSidebar={() => {}} />);

    fireEvent.click(screen.getByLabelText("Help"));

    expect(screen.getByText("info@infinitypay.me")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in email app" })).toHaveAttribute(
      "href",
      "mailto:info@infinitypay.me",
    );
  });
});
