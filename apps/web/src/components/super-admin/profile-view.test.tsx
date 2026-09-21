import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateUser = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { updateUser },
  }),
}));

describe("ProfileView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    updateUser.mockResolvedValue({ error: null });
  });

  it("shows the admin's email and role as Super Admin", async () => {
    const { ProfileView } = await import("./profile-view");
    render(<ProfileView email="ceo@infinitypay.me" fullName="Amina CEO" />);

    expect(screen.getByText("ceo@infinitypay.me")).toBeInTheDocument();
    expect(screen.getByText("Super Admin")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Amina CEO")).toBeInTheDocument();
  });

  it("saves a new full name via Supabase Auth on Save Profile", async () => {
    const { ProfileView } = await import("./profile-view");
    render(<ProfileView email="ceo@infinitypay.me" fullName="Amina CEO" />);

    fireEvent.change(screen.getByDisplayValue("Amina CEO"), { target: { value: "Amina Mwakalinga" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Profile" }));

    await waitFor(() => expect(updateUser).toHaveBeenCalledWith({ data: { full_name: "Amina Mwakalinga" } }));
    await waitFor(() => expect(screen.getByText("Profile updated.")).toBeInTheDocument());
  });

  it("rejects a blank full name without calling Supabase", async () => {
    const { ProfileView } = await import("./profile-view");
    render(<ProfileView email="ceo@infinitypay.me" fullName="Amina CEO" />);

    fireEvent.change(screen.getByDisplayValue("Amina CEO"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Save Profile" }));

    await waitFor(() => expect(screen.getByText("Full name cannot be blank.")).toBeInTheDocument());
    expect(updateUser).not.toHaveBeenCalled();
  });
});
