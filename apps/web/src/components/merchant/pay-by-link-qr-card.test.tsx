import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const toDataURLMock = vi.fn().mockResolvedValue("data:image/png;base64,mockqr");
const toCanvasMock = vi.fn().mockResolvedValue(undefined);

vi.mock("qrcode", () => ({
  default: {
    toDataURL: (...args: unknown[]) => toDataURLMock(...args),
    toCanvas: (...args: unknown[]) => toCanvasMock(...args),
  },
}));

const addImageMock = vi.fn();
const textMock = vi.fn();
const saveMock = vi.fn();
const splitTextToSizeMock = vi.fn((text: string) => [text]);

// vi.fn() can't be used as a constructor (jsPDF is instantiated via
// `new`) — a real class, not a mocked arrow-function factory, is what
// makes `new jsPDF(...)` work at all under the mock.
class MockJsPDF {
  internal = { pageSize: { getWidth: () => 210, getHeight: () => 297 } };
  setFont() {
    return this;
  }
  setFontSize() {
    return this;
  }
  setTextColor() {
    return this;
  }
  addImage(...args: unknown[]) {
    addImageMock(...args);
    return this;
  }
  text(...args: unknown[]) {
    textMock(...args);
    return this;
  }
  splitTextToSize(text: string) {
    return splitTextToSizeMock(text);
  }
  save(...args: unknown[]) {
    saveMock(...args);
  }
}

vi.mock("jspdf", () => ({
  jsPDF: MockJsPDF,
}));

// jsdom has no real canvas — fetch() for the logo asset would also fail
// without a mock; return "not found" so the PDF path falls back to
// "no logo" cleanly, same as a real offline/missing-asset case.
vi.stubGlobal(
  "fetch",
  vi.fn().mockResolvedValue({ ok: false }),
);

describe("PayByLinkQrCard", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows the exact required instruction and print-helper text", async () => {
    const { PayByLinkQrCard } = await import("./pay-by-link-qr-card");
    render(
      <PayByLinkQrCard
        merchantName="Paul Masanja"
        slug="paul-masanja"
        publicUrl="https://infinitypay.me/pay/paul-masanja"
      />,
    );

    expect(
      screen.getByText("Scan with your camera or barcode scanner to open the Pay by Link page."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Print this on a poster, table tent, or receipt — anyone who scans it with a phone camera or barcode scanner lands on your Pay by Link page.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a Download QR PDF button and generates a PDF named after the merchant slug", async () => {
    const { PayByLinkQrCard } = await import("./pay-by-link-qr-card");
    render(
      <PayByLinkQrCard
        merchantName="Paul Masanja"
        slug="paul-masanja"
        publicUrl="https://infinitypay.me/pay/paul-masanja"
      />,
    );

    const button = screen.getByRole("button", { name: /Download QR PDF/ });
    fireEvent.click(button);

    await waitFor(() => expect(saveMock).toHaveBeenCalledWith("pay-by-link-paul-masanja.pdf"));
    expect(toDataURLMock).toHaveBeenCalledWith(
      "https://infinitypay.me/pay/paul-masanja",
      expect.objectContaining({ width: expect.any(Number) }),
    );
    // The QR image and the instruction text both make it into the PDF —
    // not just a bare "it didn't crash" check.
    expect(addImageMock).toHaveBeenCalled();
    expect(textMock.mock.calls.some((call) => call[0] === "https://infinitypay.me/pay/paul-masanja")).toBe(true);
  });

  it("shows the missing-QR message and disables the button when there is no public URL yet", async () => {
    const { PayByLinkQrCard } = await import("./pay-by-link-qr-card");
    render(<PayByLinkQrCard merchantName="Paul Masanja" slug="paul-masanja" publicUrl="" />);

    expect(screen.getByText("Pay by Link QR code is not available yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download QR PDF/ })).toBeDisabled();
  });

  it("shows a generation-failed message if PDF creation throws", async () => {
    toDataURLMock.mockRejectedValueOnce(new Error("boom"));
    const { PayByLinkQrCard } = await import("./pay-by-link-qr-card");
    render(
      <PayByLinkQrCard
        merchantName="Paul Masanja"
        slug="paul-masanja"
        publicUrl="https://infinitypay.me/pay/paul-masanja"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Download QR PDF/ }));

    await waitFor(() =>
      expect(screen.getByText("QR PDF could not be generated. Please try again.")).toBeInTheDocument(),
    );
  });
});
