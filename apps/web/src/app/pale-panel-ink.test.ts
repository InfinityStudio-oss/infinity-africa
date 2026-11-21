import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * A pale panel on a dark page must declare its ink.
 *
 * Most of the app sits on the navy gradient, so the default text colour
 * is light. A panel with a near-white background and no `text-*` of its
 * own inherits that and renders light-on-light. globals.css answers this
 * with a zero-specificity `:where(...)` rule that gives known pale
 * surfaces dark ink — it loses to any explicit text utility, so it can
 * only help.
 *
 * That rule listed the app's own surface tokens only. A banner written
 * straight from the Tailwind palette slipped past it, which is how the
 * Payouts page shipped "Sandbox. These payouts are simulated" in pale
 * yellow on pale yellow — invisible, on the one notice that tells
 * someone no real money is moving.
 *
 * This test is the thing that was missing: it reads the components, not
 * the stylesheet, so a new pale background anywhere has to be covered
 * before it can ship.
 */

const SRC = join(process.cwd(), "src");
const GLOBALS = join(SRC, "app", "globals.css");

/** Tailwind palette backgrounds pale enough to need dark ink. */
const PALE_BG = /\bbg-(amber|red|emerald|green|blue|yellow|orange|lime|teal|cyan|sky|indigo|violet|pink|rose|slate|gray|zinc|neutral|stone)-(50|100)\b/g;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return full.endsWith(".tsx") && !full.endsWith(".test.tsx") ? [full] : [];
  });
}

describe("pale panels declare their ink", () => {
  it("every pale Tailwind background in use is covered by the globals rule", () => {
    const css = readFileSync(GLOBALS, "utf8");
    // The one zero-specificity block that hands out dark ink.
    const rule = css.slice(css.indexOf(":where("), css.indexOf("color: var(--color-on-surface);"));

    const missing = new Map<string, string[]>();
    for (const file of walk(SRC)) {
      const source = readFileSync(file, "utf8");
      for (const used of source.match(PALE_BG) ?? []) {
        // An element that sets its own text colour is already explicit,
        // but we cannot tell which element a class belongs to from a
        // regex over the file. Covering the class in the rule is the
        // safe answer either way: an explicit text-* still wins.
        if (!rule.includes(`.${used},`) && !rule.includes(`.${used}\n`)) {
          const where = missing.get(used) ?? [];
          where.push(file.slice(SRC.length + 1));
          missing.set(used, where);
        }
      }
    }

    expect(
      Object.fromEntries(missing),
      "add these to the :where(...) ink rule in globals.css, or give the element an explicit text-* colour",
    ).toEqual({});
  });

  it("the sandbox notice on the Payouts page is one of them", () => {
    // Named explicitly because this is the one that shipped broken, and
    // a regression here is silent: the page still renders, the words are
    // just not there.
    const page = readFileSync(join(SRC, "app", "portal", "payouts", "page.tsx"), "utf8");
    expect(page).toContain("bg-amber-50");

    const css = readFileSync(GLOBALS, "utf8");
    const rule = css.slice(css.indexOf(":where("), css.indexOf("color: var(--color-on-surface);"));
    expect(rule).toContain(".bg-amber-50,");
  });
});
