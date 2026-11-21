import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopyButton } from "./copy-button";

/**
 * The thing most often copied here is a secret shown exactly once. A
 * copy button that quietly fails costs the person the credential: they
 * click, see nothing change, dismiss the panel, and the only copy of
 * the key is gone.
 *
 * So the failure path is tested as carefully as the happy one.
 * navigator.clipboard is undefined outside a secure context, rejects
 * when the document is not focused, and can be blocked by permissions
 * policy — none of which is exotic.
 */

function setClipboard(impl: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    value: impl,
    configurable: true,
    writable: true,
  });
}

afterEach(() => {
  setClipboard(undefined);
  vi.restoreAllMocks();
});

describe("CopyButton", () => {
  it("writes the value and confirms it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });

    render(<CopyButton value="sk_test_abc123" describes="payout key" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy payout key" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("sk_test_abc123"));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("announces the copy to a screen reader, not just with a tick", async () => {
    setClipboard({ writeText: vi.fn().mockResolvedValue(undefined) });

    render(<CopyButton value="sk_test_abc123" describes="payout key" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy payout key" }));

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("payout key copied to the clipboard"),
    );
  });

  it("says so when the clipboard is not available at all", async () => {
    // Undefined is the ordinary case on plain http, not an edge case.
    setClipboard(undefined);

    render(<CopyButton value="sk_test_abc123" describes="payout key" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy payout key" }));

    expect(await screen.findByText(/Couldn't reach the clipboard/)).toBeInTheDocument();
    expect(screen.queryByText("Copied")).not.toBeInTheDocument();
  });

  it("says so when the write is rejected", async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("not focused")) });

    render(<CopyButton value="sk_test_abc123" describes="payout key" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy payout key" }));

    expect(await screen.findByText(/Couldn't reach the clipboard/)).toBeInTheDocument();
  });

  it("selects the text when it cannot copy, so it can still be taken by hand", async () => {
    setClipboard(undefined);
    const addRange = vi.fn();
    vi.spyOn(window, "getSelection").mockReturnValue({
      removeAllRanges: vi.fn(),
      addRange,
    } as unknown as Selection);

    render(
      <>
        <code id="copyable-payout-key">sk_test_abc123</code>
        <CopyButton value="sk_test_abc123" describes="payout key" />
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy payout key" }));

    // A dead end becomes two keystrokes.
    await waitFor(() => expect(addRange).toHaveBeenCalled());
  });

  it("never reports success when nothing was written", async () => {
    const onCopied = vi.fn();
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("blocked")) });

    render(<CopyButton value="sk_test_abc123" describes="payout key" onCopied={onCopied} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy payout key" }));

    await screen.findByText(/Couldn't reach the clipboard/);
    expect(onCopied).not.toHaveBeenCalled();
  });
});
