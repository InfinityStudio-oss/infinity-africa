import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { InvoiceStatus } from "@infinity/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Invoice } from "@/lib/portal/types";

const listInvoices = vi.fn();
const createInvoice = vi.fn();
const generateInvoicePaymentLink = vi.fn();

vi.mock("@/lib/portal/api", () => ({
  listInvoices: (...args: unknown[]) => listInvoices(...args),
  createInvoice: (...args: unknown[]) => createInvoice(...args),
  generateInvoicePaymentLink: (...args: unknown[]) => generateInvoicePaymentLink(...args),
}));

function invoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: "inv-1",
    merchant_id: "merchant-1",
    customer_id: null,
    invoice_number: "INV-1044",
    customer_name: "Amina Hassan",
    customer_email: "amina@example.com",
    customer_phone: null,
    due_date: "2026-09-01",
    currency: "TZS",
    subtotal: "1000.00",
    tax_amount: "0.00",
    discount_amount: "0.00",
    total_amount: "1000.00",
    amount_paid: "0.00",
    status: InvoiceStatus.SENT,
    payment_link_id: "link-1",
    notes: null,
    created_at: "2026-08-26T09:00:00Z",
    updated_at: "2026-08-26T09:00:00Z",
    sent_at: "2026-08-26T09:00:05Z",
    items: [],
    ...overrides,
  };
}

async function fillAndSubmitInvoiceForm(container: HTMLElement, { withEmail = true } = {}) {
  fireEvent.change(screen.getByPlaceholderText("e.g. Juma Traders Ltd"), { target: { value: "Amina Hassan" } });
  if (withEmail) {
    fireEvent.change(screen.getByPlaceholderText("customer@example.com"), { target: { value: "amina@example.com" } });
  } else {
    fireEvent.change(screen.getByPlaceholderText("+255 7XX XXX XXX"), { target: { value: "+255700000000" } });
  }
  // The form starts with two empty line-item rows — only the first needs
  // filling in for the invoice to be valid.
  fireEvent.change(screen.getAllByPlaceholderText("e.g. Wholesale delivery — 50kg bags")[0], {
    target: { value: "Consulting services" },
  });
  fireEvent.change(screen.getAllByPlaceholderText("70,000")[0], { target: { value: "1000" } });
  const dateInput = container.querySelector('input[type="date"]') as HTMLInputElement;
  fireEvent.change(dateInput, { target: { value: "2026-09-01" } });

  fireEvent.click(screen.getByRole("button", { name: /Send Invoice Email/ }));
}

describe("InvoicesView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listInvoices.mockResolvedValue([]);
  });

  it("renders the Send Invoice Email button, not the old Pay Now wording", async () => {
    const { InvoicesView } = await import("./invoices-view");
    render(<InvoicesView />);

    await waitFor(() => expect(listInvoices).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /Send Invoice Email/ })).toBeInTheDocument();
    expect(screen.queryByText(/Send Invoice with Pay Now Link/)).not.toBeInTheDocument();
  });

  it("shows the real customer-facing copy instead of the fake pay.infinitypay.me domain", async () => {
    const { InvoicesView } = await import("./invoices-view");
    render(<InvoicesView />);

    await waitFor(() => expect(listInvoices).toHaveBeenCalled());
    expect(screen.getByText("Customer will receive an invoice email with a secure Pay Now link.")).toBeInTheDocument();
    expect(screen.queryByText(/pay\.infinitypay\.me/)).not.toBeInTheDocument();
  });

  it("shows a success message once the invoice email is sent", async () => {
    createInvoice.mockResolvedValue(invoice());
    const { InvoicesView } = await import("./invoices-view");
    const { container } = render(<InvoicesView />);
    await waitFor(() => expect(listInvoices).toHaveBeenCalled());

    await fillAndSubmitInvoiceForm(container);

    await waitFor(() => expect(createInvoice).toHaveBeenCalled());
    expect(createInvoice).toHaveBeenCalledWith(
      expect.objectContaining({ customer_email: "amina@example.com", send_now: true }),
    );
    expect(await screen.findByText("Invoice email sent to customer.")).toBeInTheDocument();
  });

  it("blocks sending and shows a clear message when no customer email is given, without calling the API", async () => {
    const { InvoicesView } = await import("./invoices-view");
    const { container } = render(<InvoicesView />);
    await waitFor(() => expect(listInvoices).toHaveBeenCalled());

    await fillAndSubmitInvoiceForm(container, { withEmail: false });

    expect(await screen.findByText("Add customer email before sending invoice.")).toBeInTheDocument();
    expect(createInvoice).not.toHaveBeenCalled();
  });

  it("shows a clear failure message when the backend rejects the send (e.g. email delivery failed)", async () => {
    createInvoice.mockRejectedValue(new Error("Couldn't send the email — the email provider rejected the request."));
    const { InvoicesView } = await import("./invoices-view");
    const { container } = render(<InvoicesView />);
    await waitFor(() => expect(listInvoices).toHaveBeenCalled());

    await fillAndSubmitInvoiceForm(container);

    expect(
      await screen.findByText("Couldn't send the email — the email provider rejected the request."),
    ).toBeInTheDocument();
  });

  it("lets a merchant save a draft without an email, with no send attempted", async () => {
    createInvoice.mockResolvedValue(invoice({ status: InvoiceStatus.DRAFT, sent_at: null }));
    const { InvoicesView } = await import("./invoices-view");
    const { container } = render(<InvoicesView />);
    await waitFor(() => expect(listInvoices).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText("e.g. Juma Traders Ltd"), { target: { value: "Amina Hassan" } });
    fireEvent.change(screen.getAllByPlaceholderText("e.g. Wholesale delivery — 50kg bags")[0], {
      target: { value: "Consulting services" },
    });
    fireEvent.change(screen.getAllByPlaceholderText("70,000")[0], { target: { value: "1000" } });
    const dateInput = container.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: "2026-09-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Save as Draft" }));

    await waitFor(() => expect(createInvoice).toHaveBeenCalledWith(expect.objectContaining({ send_now: false })));
    expect(screen.queryByText("Invoice email sent to customer.")).not.toBeInTheDocument();
  });
});
