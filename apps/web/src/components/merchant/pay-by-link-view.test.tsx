import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PayByLink } from "@/lib/portal/types";

const getMyPayByLink = vi.fn();
const getMyMerchant = vi.fn();
const createPayByLink = vi.fn();
const updatePayByLink = vi.fn();
const checkPayByLinkSlugAvailability = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  getMyPayByLink: (...args: unknown[]) => getMyPayByLink(...args),
  getMyMerchant: (...args: unknown[]) => getMyMerchant(...args),
  createPayByLink: (...args: unknown[]) => createPayByLink(...args),
  updatePayByLink: (...args: unknown[]) => updatePayByLink(...args),
  checkPayByLinkSlugAvailability: (...args: unknown[]) => checkPayByLinkSlugAvailability(...args),
}));

// The QR/PDF card has its own dedicated test file
// (pay-by-link-qr-card.test.tsx) — stubbed here so this file stays
// focused on the surrounding management panel (copy/share/preview/edit),
// and confirms only that the real Pay by Link data reaches it.
vi.mock("./pay-by-link-qr-card", () => ({
  PayByLinkQrCard: ({ merchantName, slug, publicUrl }: { merchantName: string; slug: string; publicUrl: string }) => (
    <div data-testid="qr-card">{`${merchantName}|${slug}|${publicUrl}`}</div>
  ),
}));

const link: PayByLink = {
  id: "link-1",
  merchant_id: "merchant-1",
  slug: "paul-masanja",
  public_url: "https://infinitypay.me/pay/paul-masanja",
  display_name: "Paul Masanja",
  description: null,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  last_used_at: null,
};

describe("PayByLinkView / ManagePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMyPayByLink.mockResolvedValue(link);
    getMyMerchant.mockResolvedValue({ business_name: "Paul Masanja" });
  });

  it("passes the real Pay by Link URL through to the QR card unchanged", async () => {
    const { PayByLinkView } = await import("./pay-by-link-view");
    render(<PayByLinkView />);

    await waitFor(() => expect(screen.getByTestId("qr-card")).toBeInTheDocument());
    expect(screen.getByTestId("qr-card").textContent).toBe(
      "Paul Masanja|paul-masanja|https://infinitypay.me/pay/paul-masanja",
    );
  });

  it("Copy link still writes the public URL to the clipboard", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    const { PayByLinkView } = await import("./pay-by-link-view");
    render(<PayByLinkView />);

    await waitFor(() => expect(screen.getByTitle("Copy link")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("Copy link"));

    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("https://infinitypay.me/pay/paul-masanja"),
    );
    expect(screen.getByText("Pay by Link copied.")).toBeInTheDocument();
  });

  it("Share on WhatsApp still links out with the public URL", async () => {
    const { PayByLinkView } = await import("./pay-by-link-view");
    render(<PayByLinkView />);

    await waitFor(() => expect(screen.getByText("Share on WhatsApp")).toBeInTheDocument());
    const shareLink = screen.getByText("Share on WhatsApp").closest("a");
    expect(shareLink?.getAttribute("href")).toContain(encodeURIComponent(link.public_url));
  });

  it("Preview still links to the public Pay by Link page", async () => {
    const { PayByLinkView } = await import("./pay-by-link-view");
    render(<PayByLinkView />);

    await waitFor(() => expect(screen.getByText("Preview")).toBeInTheDocument());
    const previewLink = screen.getByText("Preview").closest("a");
    expect(previewLink?.getAttribute("href")).toBe(link.public_url);
  });

  it("Edit still opens the edit form", async () => {
    const { PayByLinkView } = await import("./pay-by-link-view");
    render(<PayByLinkView />);

    await waitFor(() => expect(screen.getByText("Edit")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Edit"));

    expect(screen.getByText("Save changes")).toBeInTheDocument();
  });
});
