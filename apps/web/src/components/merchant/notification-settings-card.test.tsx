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
  collection_sms_enabled: false,
  announcement_sms_enabled: true,
  sms_notification_phone: null,
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
  });

  it("offers one address, not two", async () => {
    // A secondary address used to be configurable here. One recipient
    // the merchant can see beats two they have to remember, and a
    // forwarding rule does the rest.
    getMyNotificationSettings.mockResolvedValue(settings);
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(screen.getByDisplayValue("owner@example.com")).toBeInTheDocument());
    expect(screen.queryByText(/Secondary notification email/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/up to 2 notification emails/i)).not.toBeInTheDocument();
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
    // The card now saves the email and SMS preferences in one request,
    // so the payload carries both. Still asserted exactly rather than
    // partially: the secondary address being explicitly null is the
    // point of the test above it, and a partial match would stop
    // catching it.
    expect(updateMyNotificationSettings).toHaveBeenCalledWith({
      primary_notification_email: "new@example.com",
      secondary_notification_email: null,
      collection_notifications_enabled: true,
      collection_sms_enabled: false,
      sms_notification_phone: "",
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

/** The merchant's own control over transactional SMS, and the number it
 * goes to. Both default off/empty: enabling SMS for 60 live merchants is
 * a cost and a consent decision, not something a deployment does. */
describe("SMS alerts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMyNotificationSettings.mockResolvedValue(settings);
    getMyMerchant.mockResolvedValue({ contact_email: "owner@shop.co.tz", contact_phone: "255799000111" });
  });

  async function renderCard() {
    const { NotificationSettingsCard } = await import("./notification-settings-card");
    render(<NotificationSettingsCard />);
  }

  it("is off until the merchant turns it on", async () => {
    await renderCard();

    const toggle = await screen.findByLabelText(/Also send me an SMS/i);
    expect(toggle).not.toBeChecked();
  });

  it("saves the preference and the number together", async () => {
    updateMyNotificationSettings.mockResolvedValue({
      ...settings,
      collection_sms_enabled: true,
      sms_notification_phone: "255712345678",
    });
    await renderCard();

    fireEvent.click(await screen.findByLabelText(/Also send me an SMS/i));
    fireEvent.change(screen.getByLabelText(/SMS number/i), {
      target: { value: "0712345678" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() =>
      expect(updateMyNotificationSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          collection_sms_enabled: true,
          sms_notification_phone: "0712345678",
        }),
      ),
    );
  });

  it("says where alerts go when no number is set", async () => {
    getMyMerchant.mockResolvedValue({ contact_email: "owner@example.com", contact_phone: "255799000111" });
    await renderCard();

    fireEvent.click(await screen.findByLabelText(/Also send me an SMS/i));

    expect(await screen.findByText(/255799000111/)).toBeInTheDocument();
  });

  it("warns when there is no number to send to at all", async () => {
    getMyMerchant.mockResolvedValue({ contact_email: "owner@example.com", contact_phone: null });
    await renderCard();

    fireEvent.click(await screen.findByLabelText(/Also send me an SMS/i));

    expect(await screen.findByText(/no number on your account/i)).toBeInTheDocument();
  });
});
