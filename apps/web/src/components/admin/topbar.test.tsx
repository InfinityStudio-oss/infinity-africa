import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/supabase/logout", () => ({
  adminLogout: vi.fn(),
}));

describe("AdminTopbar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the signed-in admin's real name, email, and role in the account menu", async () => {
    const { AdminTopbar } = await import("./topbar");
    render(<AdminTopbar onOpenSidebar={() => {}} adminEmail="ceo@infinitypay.me" adminFullName="Amina CEO" />);

    fireEvent.click(screen.getByLabelText("Account menu"));

    // "Amina CEO" appears twice once the menu is open: once as the
    // always-visible topbar label next to the avatar, and once inside the
    // dropdown's identity header — the dropdown copy renders last in the DOM.
    await waitFor(() => expect(screen.getAllByText("Amina CEO").length).toBeGreaterThan(1));
    const menu = screen.getAllByText("Amina CEO").at(-1)!.closest("div")!.parentElement as HTMLElement;
    expect(within(menu).getByText("ceo@infinitypay.me")).toBeInTheDocument();
    expect(within(menu).getByText("Super Admin")).toBeInTheDocument();
    expect(within(menu).getByRole("button", { name: "Log out" })).toBeInTheDocument();
    expect(within(menu).getByRole("link", { name: "Profile" })).toHaveAttribute("href", "/super-admin/profile");
    expect(within(menu).getByRole("link", { name: "Change Password" })).toHaveAttribute(
      "href",
      "/super-admin/settings",
    );
  });

  it("falls back to an email-derived initial when no full name is set yet", async () => {
    const { AdminTopbar } = await import("./topbar");
    render(<AdminTopbar onOpenSidebar={() => {}} adminEmail="ceo@infinitypay.me" adminFullName={null} />);

    expect(screen.getByLabelText("Account menu")).toHaveTextContent("C");
  });

  /**
   * The search box used to be decoration: no value, no onChange, no
   * form, no handler. An admin could type into it and press Enter and
   * nothing whatsoever happened, while the placeholder advertised a
   * search across businesses, transactions and invoices.
   *
   * These assert the two halves of the repair — that it navigates, and
   * that it only claims what it does.
   */
  describe("the search box", () => {
    it("searches businesses on submit", async () => {
      const { AdminTopbar } = await import("./topbar");
      render(<AdminTopbar onOpenSidebar={() => {}} adminEmail="ceo@infinitypay.me" />);

      const input = screen.getByRole("searchbox", { name: /search businesses/i });
      fireEvent.change(input, { target: { value: "Hotspot" } });
      fireEvent.submit(input.closest("form")!);

      expect(push).toHaveBeenCalledWith("/super-admin/merchants?search=Hotspot");
    });

    it("escapes the term rather than pasting it into the URL raw", async () => {
      const { AdminTopbar } = await import("./topbar");
      render(<AdminTopbar onOpenSidebar={() => {}} adminEmail="ceo@infinitypay.me" />);

      const input = screen.getByRole("searchbox", { name: /search businesses/i });
      fireEvent.change(input, { target: { value: "Benny & Co" } });
      fireEvent.submit(input.closest("form")!);

      expect(push).toHaveBeenCalledWith("/super-admin/merchants?search=Benny%20%26%20Co");
    });

    it("clears the filter on an empty submit instead of searching for nothing", async () => {
      const { AdminTopbar } = await import("./topbar");
      render(<AdminTopbar onOpenSidebar={() => {}} adminEmail="ceo@infinitypay.me" />);

      const input = screen.getByRole("searchbox", { name: /search businesses/i });
      fireEvent.change(input, { target: { value: "   " } });
      fireEvent.submit(input.closest("form")!);

      expect(push).toHaveBeenCalledWith("/super-admin/merchants");
    });

    it("does not promise searches it cannot perform", async () => {
      const { AdminTopbar } = await import("./topbar");
      render(<AdminTopbar onOpenSidebar={() => {}} adminEmail="ceo@infinitypay.me" />);

      const input = screen.getByRole("searchbox", { name: /search businesses/i });
      expect(input.getAttribute("placeholder")).not.toMatch(/transactions|invoices/i);
    });
  });
});
