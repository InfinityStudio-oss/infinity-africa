import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/logout", () => ({
  adminLogout: vi.fn(),
}));

describe("AdminTopbar", () => {
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
});
