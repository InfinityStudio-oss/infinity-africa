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
    expect(screen.getByText("help@infinityafrica.net")).toBeInTheDocument();
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
});
