import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NotificationSettings } from "@/lib/portal/types";

const getMyNotificationSettings = vi.fn();
const updateMyNotificationSettings = vi.fn();
const getMyMerchant = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  getMyNotificationSettings: (...args: unknown[]) => getMyNotificationSettings(...args),
  updateMyNotificationSettings: (...args: unknown[]) => updateMyNotificationSettings(...args),
  getMyMerchant: (...args: unknown[]) => getMyMerchant(...args),
}));

const settings: NotificationSettings = {
  id: "settings-1",
  merchant_id: "merchant-1",
  primary_notification_email: "owner@example.com",
  secondary_notification_email: null,
  collection_notifications_enabled: true,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  updated_by: null,
};

describe("NotificationSettingsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMyMerchant.mockResolvedValue({ contact_email: "owner@shop.co.tz" });
  });

  it("shows the required helper text and the configured primary email", async () => {
    getMyNotificationSettings.mockResolvedValue(settings);
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(screen.getByDisplayValue("owner@example.com")).toBeInTheDocument());
    expect(
      screen.getByText(
        "We will send confirmation emails to these addresses when collection payments are successfully confirmed.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Receive collection transaction notifications by email.")).toBeInTheDocument();
    expect(screen.getByText("You can add up to 2 notification emails.")).toBeInTheDocument();
  });

  it("defaults to enabled with empty fields when nothing is configured yet", async () => {
    getMyNotificationSettings.mockResolvedValue(null);
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(screen.getByLabelText(/Receive collection transaction/)).toBeChecked());
    expect(screen.getByPlaceholderText("e.g. owner@yourbusiness.com")).toHaveValue("");
  });

  it("shows the exact success message after a successful save", async () => {
    getMyNotificationSettings.mockResolvedValue(settings);
    updateMyNotificationSettings.mockResolvedValue({ ...settings, primary_notification_email: "new@example.com" });
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(screen.getByDisplayValue("owner@example.com")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("e.g. owner@yourbusiness.com"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.getByText("Notification settings saved.")).toBeInTheDocument());
    expect(updateMyNotificationSettings).toHaveBeenCalledWith({
      primary_notification_email: "new@example.com",
      secondary_notification_email: null,
      collection_notifications_enabled: true,
    });
  });

  it("surfaces the backend's exact error message instead of doing nothing", async () => {
    getMyNotificationSettings.mockResolvedValue(settings);
    updateMyNotificationSettings.mockRejectedValue(new Error("Duplicate notification emails are not allowed."));
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(screen.getByDisplayValue("owner@example.com")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(screen.getByText("Duplicate notification emails are not allowed.")).toBeInTheDocument(),
    );
  });

  // --- the page must say where notifications actually go ------------------

  it("names the account email as the recipient when no address is set", async () => {
    // The toggle defaults on with both fields empty, and the backend falls
    // back to the account email — so the page has to say so rather than
    // showing an enabled switch that looks like it sends nowhere.
    getMyNotificationSettings.mockResolvedValue({
      ...settings,
      primary_notification_email: null,
      secondary_notification_email: null,
    });
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);

    await waitFor(() =>
      expect(screen.getByText(/confirmations go to your account email/)).toBeInTheDocument(),
    );
    expect(screen.getByText("owner@shop.co.tz")).toBeInTheDocument();
  });

  it("drops that note once an address is entered", async () => {
    getMyNotificationSettings.mockResolvedValue({
      ...settings,
      primary_notification_email: null,
      secondary_notification_email: null,
    });
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);

    await waitFor(() =>
      expect(screen.getByText(/confirmations go to your account email/)).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByPlaceholderText("e.g. owner@yourbusiness.com"), {
      target: { value: "finance@shop.co.tz" },
    });

    expect(screen.queryByText(/confirmations go to your account email/)).not.toBeInTheDocument();
  });

  it("does not claim a fallback when notifications are switched off", async () => {
    getMyNotificationSettings.mockResolvedValue({
      ...settings,
      primary_notification_email: null,
      secondary_notification_email: null,
      collection_notifications_enabled: false,
    });
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(getMyNotificationSettings).toHaveBeenCalled());
    expect(screen.queryByText(/confirmations go to your account email/)).not.toBeInTheDocument();
  });
});
