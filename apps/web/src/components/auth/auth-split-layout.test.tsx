import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("AuthSplitLayout", () => {
  it("widens the left branding panel to 52% and lets the right column take the remaining space", async () => {
    const { AuthSplitLayout } = await import("./auth-split-layout");
    const { container } = render(<AuthSplitLayout>form content</AuthSplitLayout>);

    const leftPanel = container.querySelector(".bg-primary.text-on-primary");
    expect(leftPanel?.className).toContain("lg:w-[52%]");
    expect(leftPanel?.className).not.toContain("lg:w-1/2");
  });

  it("shifts the form card left within the right column at wide desktop widths without touching mobile spacing", async () => {
    const { AuthSplitLayout } = await import("./auth-split-layout");
    const { container } = render(<AuthSplitLayout>form content</AuthSplitLayout>);

    const rightColumn = container.querySelector(".bg-surface-container");
    expect(rightColumn?.className).toContain("xl:pl-8");
    expect(rightColumn?.className).toContain("xl:pr-16");
    expect(rightColumn?.className).toContain("px-4");
  });

  it("still renders the brand contact details and the form card", async () => {
    const { AuthSplitLayout } = await import("./auth-split-layout");
    render(<AuthSplitLayout>form content</AuthSplitLayout>);

    expect(screen.getAllByText("InfinityPay").length).toBeGreaterThan(0);
    expect(screen.getByText("help@infinitypay.me")).toBeInTheDocument();
    expect(screen.getByText("+255 747 730 270")).toBeInTheDocument();
    expect(screen.getByText("Mbezi - Ubungo - Dar es Salaam")).toBeInTheDocument();
    expect(screen.getByText("Back to website")).toBeInTheDocument();
    expect(screen.getByText("form content")).toBeInTheDocument();
  });

  it("keeps the Back to website link and the card inside the same width-constrained column", async () => {
    const { AuthSplitLayout } = await import("./auth-split-layout");
    render(<AuthSplitLayout maxWidthClassName="max-w-md">form content</AuthSplitLayout>);

    const backLink = screen.getByText("Back to website").closest("a");
    const column = backLink?.closest(".max-w-md");
    expect(column).not.toBeNull();
    expect(column?.querySelector("a")).toBe(backLink);
    expect(column?.textContent).toContain("form content");
  });

  it("drops the brand panel when asked, keeping the card and the back link", async () => {
    const { AuthSplitLayout } = await import("./auth-split-layout");
    const { container } = render(<AuthSplitLayout showBrandPanel={false}>form content</AuthSplitLayout>);

    expect(container.querySelector(".bg-primary.text-on-primary")).toBeNull();
    expect(screen.queryByText("help@infinitypay.me")).not.toBeInTheDocument();
    expect(screen.getByText("Back to website")).toBeInTheDocument();
    expect(screen.getByText("form content")).toBeInTheDocument();
  });

  it("centres the card evenly once there is no panel to sit beside", async () => {
    // The asymmetric xl padding exists to nudge the card left, toward the
    // panel. With no panel it would just look off-centre on a wide screen.
    const { AuthSplitLayout } = await import("./auth-split-layout");
    const { container } = render(<AuthSplitLayout showBrandPanel={false}>form content</AuthSplitLayout>);

    const column = container.querySelector(".bg-surface-container");
    expect(column?.className).not.toContain("xl:pl-8");
    expect(column?.className).not.toContain("xl:pr-16");
    expect(column?.className).toContain("px-4");
  });

  it("keeps the panel by default, so the sign-in pages are unaffected", async () => {
    const { AuthSplitLayout } = await import("./auth-split-layout");
    const { container } = render(<AuthSplitLayout>form content</AuthSplitLayout>);

    expect(container.querySelector(".bg-primary.text-on-primary")).not.toBeNull();
  });
});
