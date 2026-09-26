import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import GoLiveChecklistPage from "./page";

describe("GoLiveChecklistPage", () => {
  it("covers credentials, integration and security", () => {
    render(<GoLiveChecklistPage />);

    expect(screen.getByText("Credentials")).toBeInTheDocument();
    expect(screen.getByText("Security best practices")).toBeInTheDocument();
    expect(screen.getAllByText(/never expose|Never expose|Never ship a secret key/i).length).toBeGreaterThan(0);
  });

  it("names no payment provider", () => {
    // Public docs describe what InfinityPay offers, not who it is built
    // on. A third party's product being unavailable is neither the
    // partner's concern nor ours to publish.
    const { container } = render(<GoLiveChecklistPage />);

    expect(container.textContent).not.toMatch(/Selcom/i);
  });

  it("states the order-paid rule matches the webhooks page", () => {
    render(<GoLiveChecklistPage />);

    expect(screen.getAllByText(/collection\.successful/).length).toBeGreaterThan(0);
  });
});
