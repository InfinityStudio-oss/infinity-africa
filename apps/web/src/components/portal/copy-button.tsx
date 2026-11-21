"use client";

import { useEffect, useRef, useState } from "react";

import { Icon } from "./icon";

/**
 * Copy one value to the clipboard, and say whether it worked.
 *
 * Shared because the thing most often copied here is a secret shown
 * exactly once — an API key, a payout key — and a copy button that
 * quietly does nothing costs the person the credential. They click,
 * see no change, click "I have copied it", and the only copy is gone.
 *
 * `navigator.clipboard` is not always there. It is undefined outside a
 * secure context, it can reject when the document is not focused, and
 * a permissions policy can block it. So the write is attempted, the
 * failure is caught, and on failure the text is selected instead with
 * a message telling the person to copy it by hand. Selecting is worth
 * more than an error: it turns a dead end into two keystrokes.
 */
export function CopyButton({
  value,
  label = "Copy",
  describes,
  className = "",
  onCopied,
}: {
  value: string;
  label?: string;
  /** What is being copied, for screen readers: "secret key", "payout key". */
  describes: string;
  className?: string;
  onCopied?: () => void;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // A timeout that fires after unmount sets state on a dead component;
  // harmless in React 18+ but it keeps the component referenced, and the
  // warning it used to produce sent people chasing nothing.
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  function flash(next: "copied" | "failed") {
    setState(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2500);
  }

  async function copy() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(value);
      flash("copied");
      onCopied?.();
    } catch {
      // Select the text so it can be copied by hand rather than leaving
      // the person with a button that did nothing.
      const node = document.getElementById(`copyable-${describes.replace(/\s+/g, "-")}`);
      if (node) {
        const range = document.createRange();
        range.selectNodeContents(node);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
      }
      flash("failed");
    }
  }

  return (
    <div className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={copy}
        aria-label={state === "copied" ? `${describes} copied` : `Copy ${describes}`}
        className={`inline-flex items-center gap-1.5 rounded-lg border border-outline-variant px-3 py-1.5 text-xs font-semibold text-on-surface hover:bg-surface-container-low ${className}`}
      >
        <Icon name={state === "copied" ? "check" : "content_copy"} className="text-[16px]" />
        {state === "copied" ? "Copied" : label}
      </button>
      {/* Announced, not just shown: a sighted user sees the tick, and
          this is how everyone else learns the copy happened. */}
      <span role="status" aria-live="polite" className="sr-only">
        {state === "copied" ? `${describes} copied to the clipboard` : ""}
      </span>
      {state === "failed" && (
        <span className="text-[11px] text-amber-700">
          Couldn&apos;t reach the clipboard — the text is selected, press Ctrl+C.
        </span>
      )}
    </div>
  );
}
