import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

describe("ContactForm", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { message: "Thanks" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  it("submits the inquiry to the backend and shows a confirmation", async () => {
    const { ContactForm } = await import("./contact-form");
    render(<ContactForm />);

    fireEvent.change(screen.getByPlaceholderText("e.g. Amani Mushi"), { target: { value: "Amani Mushi" } });
    fireEvent.change(screen.getByPlaceholderText("e.g. Amani Traders Ltd"), { target: { value: "Amani Traders" } });
    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), { target: { value: "amani@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("+255 7XX XXX XXX"), { target: { value: "+255700000000" } });
    fireEvent.change(screen.getByPlaceholderText("Tell us about your business and what you need"), {
      target: { value: "I need mobile money collection." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Message" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/v1/public/inquiries");
    const body = JSON.parse(init.body);
    expect(body.full_name).toBe("Amani Mushi");
    expect(body.email).toBe("amani@example.com");
    expect(body.source).toBe("contact_page");

    expect(await screen.findByText(/we've received your message/)).toBeInTheDocument();
  });

  it("requires name, email, and a message before submitting", async () => {
    const { ContactForm } = await import("./contact-form");
    render(<ContactForm />);

    // Full Name/Email/Message are all `required` — the browser blocks
    // submission and reports the first empty one natively before our own
    // onSubmit handler ever runs, so nothing reaches the backend.
    fireEvent.click(screen.getByRole("button", { name: "Send Message" }));

    expect(screen.getByPlaceholderText("e.g. Amani Mushi")).toBeInvalid();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a whitespace-only message even though the field is technically filled", async () => {
    // required alone wouldn't catch " " — this is what the extra .trim()
    // check in handleSubmit exists for.
    const { ContactForm } = await import("./contact-form");
    render(<ContactForm />);

    fireEvent.change(screen.getByPlaceholderText("e.g. Amani Mushi"), { target: { value: "Amani Mushi" } });
    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), { target: { value: "amani@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Tell us about your business and what you need"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Message" }));

    expect(await screen.findByText(/Please fill in your name, email/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows an error with the info@ fallback address when the request fails", async () => {
    fetchMock.mockResolvedValue({ ok: false, json: async () => ({ success: false }) });
    const { ContactForm } = await import("./contact-form");
    render(<ContactForm />);

    fireEvent.change(screen.getByPlaceholderText("e.g. Amani Mushi"), { target: { value: "Amani" } });
    fireEvent.change(screen.getByPlaceholderText("you@business.co.tz"), { target: { value: "amani@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Tell us about your business and what you need"), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Message" }));

    expect(await screen.findByText(/info@infinitypay\.me/)).toBeInTheDocument();
  });
});
