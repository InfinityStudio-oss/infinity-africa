import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

vi.mock("./live-api", () => ({
  getAdminMerchantNotificationSettings: vi.fn(),
  updateAdminMerchantNotificationSettings: vi.fn(),
}));

/**
 * The switch in Super Admin → Notifications → Email writes through
 * PATCH /v1/admin/merchants/{id}/notification-settings, whose body is a
 * whole-record shape: an address left out of the request is stored as
 * NULL, not left alone. A one-click toggle that forgot to carry the two
 * configured addresses would therefore delete them — silently, because
 * the table does not show them and the operator only asked to flip a
 * switch.
 */
describe("setCollectionEmailsEnabledAction", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
  });

  async function load() {
    const api = await import("./live-api");
    const { setCollectionEmailsEnabledAction } = await import("./live-actions");
    return { api, setCollectionEmailsEnabledAction };
  }

  it("carries the stored addresses through, so switching off never deletes them", async () => {
    const { api, setCollectionEmailsEnabledAction } = await load();
    vi.mocked(api.getAdminMerchantNotificationSettings).mockResolvedValue({
      primary_notification_email: "finance@benny.co.tz",
      secondary_notification_email: "owner@benny.co.tz",
      collection_notifications_enabled: true,
    } as never);
    vi.mocked(api.updateAdminMerchantNotificationSettings).mockResolvedValue({} as never);

    const result = await setCollectionEmailsEnabledAction("merchant-1", false);

    expect(result).toEqual({ error: null });
    expect(api.updateAdminMerchantNotificationSettings).toHaveBeenCalledWith("merchant-1", {
      primary_notification_email: "finance@benny.co.tz",
      secondary_notification_email: "owner@benny.co.tz",
      collection_notifications_enabled: false,
    });
  });

  it("reads the addresses from the server, not from whatever the browser posted", async () => {
    const { api, setCollectionEmailsEnabledAction } = await load();
    vi.mocked(api.getAdminMerchantNotificationSettings).mockResolvedValue({
      primary_notification_email: "real@benny.co.tz",
      secondary_notification_email: null,
    } as never);
    vi.mocked(api.updateAdminMerchantNotificationSettings).mockResolvedValue({} as never);

    await setCollectionEmailsEnabledAction("merchant-1", true);

    expect(api.getAdminMerchantNotificationSettings).toHaveBeenCalledWith("merchant-1");
    const [, body] = vi.mocked(api.updateAdminMerchantNotificationSettings).mock.calls[0];
    expect(body.primary_notification_email).toBe("real@benny.co.tz");
  });

  it("leaves frequency and SMS alone — an absent field means unchanged", async () => {
    const { api, setCollectionEmailsEnabledAction } = await load();
    vi.mocked(api.getAdminMerchantNotificationSettings).mockResolvedValue({
      primary_notification_email: null,
      secondary_notification_email: null,
    } as never);
    vi.mocked(api.updateAdminMerchantNotificationSettings).mockResolvedValue({} as never);

    await setCollectionEmailsEnabledAction("merchant-1", false);

    const [, body] = vi.mocked(api.updateAdminMerchantNotificationSettings).mock.calls[0];
    expect(body).not.toHaveProperty("collection_notification_frequency");
    expect(body).not.toHaveProperty("collection_sms_enabled");
    expect(body).not.toHaveProperty("announcement_sms_enabled");
    expect(body).not.toHaveProperty("sms_notification_phone");
  });

  it("writes nothing at all when the current settings cannot be read", async () => {
    const { api, setCollectionEmailsEnabledAction } = await load();
    // Null is a network/auth failure, never "not configured" — the
    // backend creates a default row on read. Saving anyway would post
    // two nulls over whatever is really stored.
    vi.mocked(api.getAdminMerchantNotificationSettings).mockResolvedValue(null);

    const result = await setCollectionEmailsEnabledAction("merchant-1", false);

    expect(api.updateAdminMerchantNotificationSettings).not.toHaveBeenCalled();
    expect(result.error).toMatch(/nothing was changed/i);
  });

  it("reports a refused save instead of pretending it worked", async () => {
    const { api, setCollectionEmailsEnabledAction } = await load();
    vi.mocked(api.getAdminMerchantNotificationSettings).mockResolvedValue({
      primary_notification_email: null,
      secondary_notification_email: null,
    } as never);
    vi.mocked(api.updateAdminMerchantNotificationSettings).mockRejectedValue(new Error("Merchant not found"));

    const result = await setCollectionEmailsEnabledAction("merchant-1", false);

    expect(result.error).toBe("Merchant not found");
  });

  it("refreshes both places the state is shown", async () => {
    const { revalidatePath } = await import("next/cache");
    const { api, setCollectionEmailsEnabledAction } = await load();
    vi.mocked(api.getAdminMerchantNotificationSettings).mockResolvedValue({
      primary_notification_email: null,
      secondary_notification_email: null,
    } as never);
    vi.mocked(api.updateAdminMerchantNotificationSettings).mockResolvedValue({} as never);

    await setCollectionEmailsEnabledAction("merchant-1", false);

    expect(revalidatePath).toHaveBeenCalledWith("/super-admin/notifications/email");
    expect(revalidatePath).toHaveBeenCalledWith("/super-admin/merchants/merchant-1");
  });
});
