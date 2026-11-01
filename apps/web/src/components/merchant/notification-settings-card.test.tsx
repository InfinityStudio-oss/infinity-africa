import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NotificationSettings } from "@/lib/portal/types";

const getMyNotificationSettings = vi.fn();
const getMyMerchant = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  getMyNotificationSettings: () => getMyNotificationSettings(),
  getMyMerchant: () => getMyMerchant(),
}));

import { NotificationSettingsCard } from "./notification-settings-card";

/**
 * This card used to be a form, and these tests used to assert that a
 * merchant could save. Collection notification settings became an
 * InfinityPay control on 2026-11-01, so the file is rewritten rather than
 * relaxed: the behaviour it pins is now that the merchant can SEE the
 * state and change nothing.
 *
 * `updateMyNotificationSettings` is not mocked here because it no longer
 * exists — if a future change reintroduces a write from this card, the
 * mock factory above will fail rather than silently allow it.
 */
const settings: NotificationSettings = {
  id: "s1",
  merchant_id: "m1",
  primary_notification_email: "finance@shop.co.tz",
  secondary_notification_email: null,
  collection_notifications_enabled: true,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
} as NotificationSettings;

describe("the merchant's notification settings card", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMyMerchant.mockResolvedValue({ contact_email: "owner@shop.co.tz" });
  });

  it("shows the state without offering to change it", async () => {
    getMyNotificationSettings.mockResolvedValue(settings);
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(screen.getByText("On")).toBeInTheDocument());
    expect(screen.getByText("finance@shop.co.tz")).toBeInTheDocument();

    // The things a form would have.
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("tells the merchant who manages it and what to do", async () => {
    getMyNotificationSettings.mockResolvedValue(settings);
    render(<NotificationSettingsCard />);

    await waitFor(() =>
      expect(
        screen.getByText(/managed by InfinityPay\. Contact support to request a change\./i),
      ).toBeInTheDocument(),
    );
  });

  it("names the account email when no notification address is set", async () => {
    // The backend falls back to the account address rather than sending
    // nothing, so a card that showed a blank would be wrong about where
    // the merchant's own emails go.
    getMyNotificationSettings.mockResolvedValue({ ...settings, primary_notification_email: null });
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(screen.getByText("owner@shop.co.tz")).toBeInTheDocument());
    expect(screen.getByText(/Your account email, because no separate notification address is set/i)).toBeInTheDocument();
  });

  it("shows no recipient when notifications are off", async () => {
    getMyNotificationSettings.mockResolvedValue({
      ...settings,
      collection_notifications_enabled: false,
    });
    render(<NotificationSettingsCard />);

    await waitFor(() => expect(screen.getByText("Off")).toBeInTheDocument());
    expect(screen.queryByText("finance@shop.co.tz")).not.toBeInTheDocument();
  });

  it("does not report Off when the read simply failed", async () => {
    // A failed request is not a disabled setting. Saying "Off" here would
    // send a merchant to support about something that is working.
    getMyNotificationSettings.mockResolvedValue(null);
    render(<NotificationSettingsCard />);

    await waitFor(() =>
      expect(screen.getByText(/Couldn't load your notification settings/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Off")).not.toBeInTheDocument();
    expect(screen.queryByText("On")).not.toBeInTheDocument();
  });

  it("survives the request throwing", async () => {
    getMyNotificationSettings.mockRejectedValue(new Error("network"));
    render(<NotificationSettingsCard />);

    await waitFor(() =>
      expect(screen.getByText(/Couldn't load your notification settings/i)).toBeInTheDocument(),
    );
  });
});
