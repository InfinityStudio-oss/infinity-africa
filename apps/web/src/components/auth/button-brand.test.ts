import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The primary call to action on every auth page wears .btn-brand, the
 * hero's navy-into-teal gradient rebuilt at button scale.
 *
 * Two things drift here, and both have happened on this project. A new
 * auth form gets written by copying an old one and keeps whatever
 * styling that one had. And a colour gets nudged without anyone
 * recomputing whether white still reads on it — which is how the
 * disabled state these buttons used to have ended up at 3.37:1, in the
 * one moment the label says "Signing in…" and somebody is watching it.
 *
 * So: one test reads the components, the other reads the stylesheet and
 * does the arithmetic.
 */

const AUTH_DIR = join(process.cwd(), "src", "components", "auth");
const GLOBALS = join(process.cwd(), "src", "app", "globals.css");

/** Forms with a submit control the person presses to continue. */
const FORMS = [
  "accept-invite-form.tsx",
  "create-account-form.tsx",
  "forgot-password-form.tsx",
  "login-form.tsx",
  "resend-verification-form.tsx",
  "reset-password-form.tsx",
  "update-password-form.tsx",
];

function read(file: string): string {
  return readFileSync(join(AUTH_DIR, file), "utf8");
}

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => channel(parseInt(h.slice(i, i + 2), 16)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("the auth call-to-action button", () => {
  it.each(FORMS)("%s uses the shared brand button", (file) => {
    expect(read(file)).toContain("btn-brand");
  });

  it("has no form left on the colour the buttons used to be", () => {
    const stragglers = readdirSync(AUTH_DIR)
      .filter((f) => f.endsWith(".tsx") && !f.endsWith(".test.tsx"))
      .filter((f) => read(f).includes("bg-primary-container text-on-primary"));
    expect(stragglers).toEqual([]);
  });

  it("never fades a brand button while it is working", () => {
    // disabled:opacity-60 composites the teal end against the pale auth
    // page and lands at 3.37:1 — under the floor, on the label that says
    // the form is submitting. The stylesheet swaps in a flat navy.
    //
    // Scoped to the brand buttons on purpose: the outline "Resend
    // verification email" secondary is allowed to fade, and a blanket
    // ban would have to be weakened or deleted the first time someone
    // adds another one.
    const faded = FORMS.flatMap((file) =>
      read(file)
        .split("\n")
        .filter((line) => line.includes("btn-brand") && line.includes("disabled:opacity-60"))
        .map((line) => `${file}: ${line.trim().slice(0, 60)}…`),
    );
    expect(faded).toEqual([]);
  });

  it("keeps white legible at every stop of the gradient, hover included", () => {
    const css = readFileSync(GLOBALS, "utf8");
    // Each .btn-brand rule on its own, rather than one slice from the
    // first to the last — a slice runs past the closing brace and picks
    // up whatever rule follows in the file, which is how this test first
    // "failed" on a pale blue that has nothing to do with the button.
    const rules = [...css.matchAll(/\.btn-brand[^{]*\{[^}]*\}/g)].map((m) => m[0]);
    expect(rules.length).toBe(3); // base, hover, disabled

    const stops = [...new Set(rules.join("\n").match(/#[0-9a-fA-F]{6}/g) ?? [])].filter(
      (hex) => hex.toLowerCase() !== "#ffffff",
    );
    // Guard the guard: if the class is ever rewritten with colour
    // functions instead of hexes, this must fail loudly rather than
    // quietly check nothing.
    expect(stops.length).toBeGreaterThanOrEqual(5);

    for (const stop of stops) {
      expect(contrast("#ffffff", stop), `white on ${stop}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
