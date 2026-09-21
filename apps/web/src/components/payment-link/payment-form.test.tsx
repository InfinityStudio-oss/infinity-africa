import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PublicPaymentLink } from "@/lib/payment-links";

import { PaymentForm } from "./payment-form";

vi.mock("qrcode", () => ({
  default: { toCanvas: vi.fn().mockResolvedValue(undefined) },
}));

const link: PublicPaymentLink = {
  merchant_name: "Test Merchant",
  amount: "25000.00",
  currency: "TZS",
  description: "Invoice for services",
  customer_name: null,
  customer_phone: null,
  expires_at: null,
  allowed_payment_methods: ["USSD_PUSH", "STK_PUSH", "SELCOM_PESA_PUSH", "DYNAMIC_QR"],
  status: "ACTIVE",
  success_redirect_url: null,
  failure_redirect_url: null,
};

describe("PaymentForm", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const QRCode = (await import("qrcode")).default;
    vi.mocked(QRCode.toCanvas).mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows PAYMENT REQUEST, amount, and description — no merchant-name eyebrow", () => {
    render(<PaymentForm slug="test-slug" link={link} />);

    expect(screen.getByText("Payment Request")).toBeInTheDocument();
    expect(screen.queryByText("Paying Test Merchant")).not.toBeInTheDocument();
    expect(screen.queryByText(/PAYING MERCHANT/i)).not.toBeInTheDocument();
    expect(screen.getByText("TZS 25,000.00")).toBeInTheDocument();
    expect(screen.getByText("Invoice for services")).toBeInTheDocument();
  });

  it("shows the InfinityPay logo mark in the header", () => {
    render(<PaymentForm slug="test-slug" link={link} />);

    expect(screen.getByText("InfinityPay")).toBeInTheDocument();
  });

  it("shows exactly the three active payment methods, nothing else", () => {
    render(<PaymentForm slug="test-slug" link={link} />);

    expect(screen.getByRole("button", { name: /Pay by Mobile Money Push/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pay with Selcom Pesa/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Scan QR \/ TanQR/ })).toBeInTheDocument();

    expect(screen.queryByText(/Hosted Checkout/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Pay securely/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Debit\/Credit Card/i)).not.toBeInTheDocument();
    expect(screen.getByText("Choose how you want to pay")).toBeInTheDocument();
  });

  it("asks for a phone number before submitting Mobile Money Push when the link has none on file", () => {
    render(<PaymentForm slug="test-slug" link={link} />);
    fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

    expect(screen.getByLabelText("Phone number")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("submits Mobile Money Push immediately when the link already has a phone on file", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          collection_id: "11111111-1111-1111-1111-111111111111",
          method: "WALLET_PUSH",
          status: "pending",
          message: "Payment prompt sent. Please approve on your phone.",
          qr: null,
          payment_token: null,
          payment_gateway_url: null,
        },
      }),
    });

    render(<PaymentForm slug="test-slug" link={{ ...link, customer_phone: "255747730270" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/public/payment-links/test-slug/pay");
    expect(String(url)).not.toContain("/pay/wallet-push");
    expect(init.headers["Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(init.body)).toEqual({ method: "WALLET_PUSH", customer_phone: "255747730270" });

    await waitFor(() => expect(screen.getByText("Payment prompt sent. Please approve on your phone.")).toBeInTheDocument());
  });

  it("submits Selcom Pesa with the typed phone number", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          collection_id: "22222222-2222-2222-2222-222222222222",
          method: "SELCOM_PESA",
          status: "pending",
          message: "Selcom Pesa prompt sent. Please approve in your Selcom Pesa app.",
          qr: null,
          payment_token: null,
          payment_gateway_url: null,
        },
      }),
    });

    render(<PaymentForm slug="test-slug" link={link} />);
    fireEvent.click(screen.getByRole("button", { name: /Pay with Selcom Pesa/ }));
    fireEvent.change(screen.getByLabelText("Phone number"), { target: { value: "0747730270" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Selcom Pesa prompt" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      method: "SELCOM_PESA",
      customer_phone: "0747730270",
    });
    await waitFor(() =>
      expect(screen.getByText("Selcom Pesa prompt sent. Please approve in your Selcom Pesa app.")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Refresh status" })).toBeInTheDocument();
  });

  it("submits Scan QR / TanQR immediately with no phone step, and renders Selcom's exact qr payload unaltered", async () => {
    const selcomQrPayload = "00020101021226580014COM.SELCOM.WWW02..."; // exact Selcom-shaped EMVCo text
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          collection_id: "33333333-3333-3333-3333-333333333333",
          method: "TANQR",
          status: "pending",
          message: "Scan this QR using your supported payment app.",
          qr: selcomQrPayload,
          payment_token: "80008000",
          payment_gateway_url: null,
        },
      }),
    });

    render(<PaymentForm slug="test-slug" link={link} />);
    fireEvent.click(screen.getByRole("button", { name: /Scan QR \/ TanQR/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ method: "TANQR", customer_phone: null });

    await waitFor(() => expect(screen.getByText("Scan this QR using your supported payment app.")).toBeInTheDocument());
    expect(screen.getByText("Token: 80008000")).toBeInTheDocument();

    const QRCode = (await import("qrcode")).default;
    expect(QRCode.toCanvas).toHaveBeenCalledWith(
      expect.anything(),
      selcomQrPayload, // the exact string Selcom returned — never re-derived from order_id/amount/url
      expect.anything(),
    );

    expect(screen.getByText("Open your supported payment app.")).toBeInTheDocument();
    expect(screen.getByText("Choose Scan QR / TanQR.")).toBeInTheDocument();
    expect(screen.getByText("Scan the QR shown here.")).toBeInTheDocument();
    expect(screen.getByText("Confirm payment in your app.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh status" })).toBeInTheDocument();
  });

  it("renders a Selcom-returned URL/image qr as an image, not a re-encoded QR", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          collection_id: "44444444-4444-4444-4444-444444444444",
          method: "TANQR",
          status: "pending",
          message: "Scan this QR using your supported payment app.",
          qr: "https://selcom.example/qr/abc123.png",
          payment_token: null,
          payment_gateway_url: null,
        },
      }),
    });

    render(<PaymentForm slug="test-slug" link={link} />);
    fireEvent.click(screen.getByRole("button", { name: /Scan QR \/ TanQR/ }));

    await waitFor(() => expect(screen.getByAltText("Selcom payment QR code")).toBeInTheDocument());
    expect(screen.getByAltText("Selcom payment QR code")).toHaveAttribute("src", "https://selcom.example/qr/abc123.png");
    const QRCode = (await import("qrcode")).default;
    expect(QRCode.toCanvas).not.toHaveBeenCalled();
  });

  it("shows a failed state with the backend's message when the attempt fails outright", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          collection_id: "11111111-1111-1111-1111-111111111111",
          method: "WALLET_PUSH",
          status: "failed",
          message: "This payment attempt failed.",
          qr: null,
          payment_token: null,
          payment_gateway_url: null,
        },
      }),
    });

    render(<PaymentForm slug="test-slug" link={{ ...link, customer_phone: "255747730270" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

    await waitFor(() => expect(screen.getByText("This payment attempt failed.")).toBeInTheDocument());
  });

  it("shows the specific validation reason instead of the generic 'Invalid request' on a 422", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({
        success: false,
        error: {
          code: "validation_error",
          message: "Invalid request",
          details: [
            {
              type: "value_error",
              loc: ["body", "customer_phone"],
              msg: "Value error, must be a valid Tanzanian phone number (e.g. 255747730270, 0747730270, or 747730270)",
              input: "not-a-phone",
            },
          ],
        },
      }),
    });

    render(<PaymentForm slug="test-slug" link={{ ...link, customer_phone: "255747730270" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

    await waitFor(() =>
      expect(
        screen.getByText("must be a valid Tanzanian phone number (e.g. 255747730270, 0747730270, or 747730270)"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Invalid request")).not.toBeInTheDocument();
  });

  it("falls back to the backend's top-level message when no field-level details are present", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({
        success: false,
        error: { code: "conflict", message: "This payment link cannot be paid (status: EXPIRED)" },
      }),
    });

    render(<PaymentForm slug="test-slug" link={{ ...link, customer_phone: "255747730270" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

    await waitFor(() =>
      expect(screen.getByText("This payment link cannot be paid (status: EXPIRED)")).toBeInTheDocument(),
    );
  });

  it("polls the collection-status endpoint and shows cancelled/rejected copy distinctly from a generic failure", async () => {
    vi.useFakeTimers();
    try {
      fetchMock
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            success: true,
            data: {
              collection_id: "col-1",
              method: "WALLET_PUSH",
              status: "pending",
              message: "Payment prompt sent. Please approve on your phone.",
              qr: null,
              payment_token: null,
              payment_gateway_url: null,
            },
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ success: true, data: { status: "user_cancelled", message: "You cancelled this payment." } }),
        });

      render(<PaymentForm slug="test-slug" link={{ ...link, customer_phone: "255747730270" }} />);
      fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

      await vi.waitFor(() =>
        expect(screen.getByText("Payment prompt sent. Please approve on your phone.")).toBeInTheDocument(),
      );
      await vi.advanceTimersByTimeAsync(3000);
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

      const [pollUrl] = fetchMock.mock.calls[1];
      expect(String(pollUrl)).toContain("/public/payment-links/test-slug/collections/col-1/status");

      await vi.waitFor(() => expect(screen.getByText("Payment cancelled")).toBeInTheDocument());
      expect(screen.getByText("You cancelled this payment.")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("the Refresh status button checks status immediately, independent of the automatic poll", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          data: {
            collection_id: "col-refresh",
            method: "WALLET_PUSH",
            status: "pending",
            message: "Payment prompt sent. Please approve on your phone.",
            qr: null,
            payment_token: null,
            payment_gateway_url: null,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, data: { status: "completed", message: "Payment completed successfully." } }),
      });

    render(<PaymentForm slug="test-slug" link={{ ...link, customer_phone: "255747730270" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

    await waitFor(() =>
      expect(screen.getByText("Payment prompt sent. Please approve on your phone.")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [pollUrl] = fetchMock.mock.calls[1];
    expect(String(pollUrl)).toContain("/public/payment-links/test-slug/collections/col-refresh/status");
    await waitFor(() => expect(screen.getByText("Payment completed")).toBeInTheDocument());
  });

  it("shows a completed state once the poll reports completed", async () => {
    vi.useFakeTimers();
    try {
      fetchMock
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            success: true,
            data: {
              collection_id: "col-2",
              method: "WALLET_PUSH",
              status: "pending",
              message: "Payment prompt sent. Please approve on your phone.",
              qr: null,
              payment_token: null,
              payment_gateway_url: null,
            },
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ success: true, data: { status: "completed", message: "Payment completed successfully." } }),
        });

      render(<PaymentForm slug="test-slug" link={{ ...link, customer_phone: "255747730270" }} />);
      fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

      await vi.waitFor(() =>
        expect(screen.getByText("Payment prompt sent. Please approve on your phone.")).toBeInTheDocument(),
      );
      await vi.advanceTimersByTimeAsync(3000);

      await vi.waitFor(() => expect(screen.getByText("Payment completed")).toBeInTheDocument());
    } finally {
      vi.useRealTimers();
    }
  });

  it("links to the receipt page once payment completes", async () => {
    vi.useFakeTimers();
    try {
      fetchMock
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            success: true,
            data: {
              collection_id: "col-3",
              method: "WALLET_PUSH",
              status: "pending",
              message: "Payment prompt sent. Please approve on your phone.",
              qr: null,
              payment_token: null,
              payment_gateway_url: null,
            },
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ success: true, data: { status: "completed", message: "Payment completed successfully." } }),
        });

      render(<PaymentForm slug="test-slug" link={{ ...link, customer_phone: "255747730270" }} />);
      fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

      await vi.waitFor(() =>
        expect(screen.getByText("Payment prompt sent. Please approve on your phone.")).toBeInTheDocument(),
      );
      await vi.advanceTimersByTimeAsync(3000);

      await vi.waitFor(() => expect(screen.getByText("Payment completed")).toBeInTheDocument());
      expect(screen.getByRole("link", { name: "View & Download Receipt" })).toHaveAttribute(
        "href",
        "/pay/test-slug/receipt/col-3",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not show a receipt link when a success_redirect_url will navigate the customer away", async () => {
    vi.useFakeTimers();
    try {
      fetchMock
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            success: true,
            data: {
              collection_id: "col-4",
              method: "WALLET_PUSH",
              status: "pending",
              message: "Payment prompt sent. Please approve on your phone.",
              qr: null,
              payment_token: null,
              payment_gateway_url: null,
            },
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ success: true, data: { status: "completed", message: "Payment completed successfully." } }),
        });

      render(
        <PaymentForm
          slug="test-slug"
          link={{ ...link, customer_phone: "255747730270", success_redirect_url: "https://merchant.example/thanks" }}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: /Pay by Mobile Money Push/ }));

      await vi.waitFor(() =>
        expect(screen.getByText("Payment prompt sent. Please approve on your phone.")).toBeInTheDocument(),
      );
      await vi.advanceTimersByTimeAsync(3000);

      await vi.waitFor(() => expect(screen.getByText("Payment completed")).toBeInTheDocument());
      expect(screen.queryByRole("link", { name: "View & Download Receipt" })).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
