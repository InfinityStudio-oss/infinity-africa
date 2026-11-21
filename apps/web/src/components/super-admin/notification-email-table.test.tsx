import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminNotificationSettingsListRow } from "@/lib/admin/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/admin/live-actions", () => ({
  setCollectionEmailsEnabledAction: vi.fn(),
}));

function row(overrides: Partial<AdminNotificationSettingsListRow> = {}): AdminNotificationSettingsListRow {
  return {
    merchant_id: "merchant-1",
    merchant_name: "GOOD NET",
    merchant_code: "27074678",
    collection_notifications_enabled: true,
    primary_notification_email: null,
    secondary_notification_email: null,
    effective_recipient: "goodluckdanstan@gmail.com",
    uses_account_email_fallback: true,
    configured: false,
    updated_at: "2026-11-21T13:47:29Z",
    ...overrides,
  };
}

function table(rows: AdminNotificationSettingsListRow[]) {
  return { rows, search: "", page: 1, totalPages: 1 };
}

describe("NotificationEmailTable — the collection-emails switch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("switches a business off in one click and tells the server", async () => {
    const { setCollectionEmailsEnabledAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setCollectionEmailsEnabledAction).mockResolvedValue({ error: null });
    const { NotificationEmailTable } = await import("./notification-email-table");

    render(<NotificationEmailTable {...table([row()])} />);

    const toggle = screen.getByRole("switch", { name: "Collection emails for GOOD NET" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toHaveTextContent("Enabled");

    fireEvent.click(toggle);

    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    expect(toggle).toHaveTextContent("Disabled");
    expect(setCollectionEmailsEnabledAction).toHaveBeenCalledWith("merchant-1", false);
  });

  it("switches a business that is off back on", async () => {
    const { setCollectionEmailsEnabledAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setCollectionEmailsEnabledAction).mockResolvedValue({ error: null });
    const { NotificationEmailTable } = await import("./notification-email-table");

    render(
      <NotificationEmailTable
        {...table([
          // How the server renders an off row: no effective recipient,
          // because while it is off there is nobody to name.
          row({ collection_notifications_enabled: false, effective_recipient: null, configured: true }),
        ])}
      />,
    );

    const toggle = screen.getByRole("switch", { name: "Collection emails for GOOD NET" });
    expect(toggle).toHaveTextContent("Disabled");

    fireEvent.click(toggle);

    await waitFor(() => expect(toggle).toHaveTextContent("Enabled"));
    expect(setCollectionEmailsEnabledAction).toHaveBeenCalledWith("merchant-1", true);
  });

  it("never leaves the pill claiming a change the server refused", async () => {
    const { setCollectionEmailsEnabledAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setCollectionEmailsEnabledAction).mockResolvedValue({
      error: "Couldn't change collection emails. Try again.",
    });
    const { NotificationEmailTable } = await import("./notification-email-table");

    render(<NotificationEmailTable {...table([row()])} />);

    const toggle = screen.getByRole("switch", { name: "Collection emails for GOOD NET" });
    fireEvent.click(toggle);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Couldn't change collection emails"));
    // Back to the truth: the server still has it enabled.
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toHaveTextContent("Enabled");
  });

  it("stops naming a recipient the moment a row is switched off", async () => {
    const { setCollectionEmailsEnabledAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setCollectionEmailsEnabledAction).mockResolvedValue({ error: null });
    const { NotificationEmailTable } = await import("./notification-email-table");

    render(<NotificationEmailTable {...table([row()])} />);
    const cells = screen.getAllByRole("row")[1];
    expect(within(cells).getByText("goodluckdanstan@gmail.com")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Collection emails for GOOD NET" }));

    // The two cells describe the same fact and must not contradict each
    // other while the save is in flight.
    await waitFor(() => expect(within(cells).getByText("Nobody — switched off")).toBeInTheDocument());
    expect(within(cells).queryByText("goodluckdanstan@gmail.com")).not.toBeInTheDocument();
  });

  it("drops the 'Default — never changed' note once the operator has changed it", async () => {
    const { setCollectionEmailsEnabledAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setCollectionEmailsEnabledAction).mockResolvedValue({ error: null });
    const { NotificationEmailTable } = await import("./notification-email-table");

    render(<NotificationEmailTable {...table([row({ configured: false })])} />);
    expect(screen.getByText("Default — never changed")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Collection emails for GOOD NET" }));

    await waitFor(() => expect(screen.queryByText("Default — never changed")).not.toBeInTheDocument());
  });

  it("gives each business its own switch, so a click cannot land on the wrong one", async () => {
    const { setCollectionEmailsEnabledAction } = await import("@/lib/admin/live-actions");
    vi.mocked(setCollectionEmailsEnabledAction).mockResolvedValue({ error: null });
    const { NotificationEmailTable } = await import("./notification-email-table");

    render(
      <NotificationEmailTable
        {...table([
          row(),
          row({ merchant_id: "merchant-2", merchant_name: "BennyWiFi", merchant_code: "27004818" }),
        ])}
      />,
    );

    fireEvent.click(screen.getByRole("switch", { name: "Collection emails for BennyWiFi" }));

    await waitFor(() => expect(setCollectionEmailsEnabledAction).toHaveBeenCalledWith("merchant-2", false));
    expect(screen.getByRole("switch", { name: "Collection emails for GOOD NET" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});
