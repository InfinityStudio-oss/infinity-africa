import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Text that sits directly on the gradient needs gradient ink.
 *
 * Inside the admin shell, `--color-on-background` is redefined to the
 * PANEL ink — correct for the 300-odd places that render inside a card,
 * wrong for anything sitting on the page itself. A heading that wears
 * it measures about 1.07:1 and simply is not there.
 *
 * This has now surfaced five times in this project, every time from
 * someone looking at a screenshot: the SMS tabs, the sandbox notice,
 * the API-keys warnings, the pale status banners, and the section
 * headings on this page. Each was fixed where it was found. This is the
 * first attempt to make the page itself keep the rule.
 *
 * Scoped to one file deliberately. A repo-wide ban on
 * `text-on-background` would be wrong — most uses are inside cards and
 * correct — and a rule that has to be weakened to pass teaches nothing.
 */

const PAGE = join(process.cwd(), "src", "app", "super-admin", "payouts", "page.tsx");

/** Lines outside any <Card>, which is where gradient ink is required. */
function gradientLevelLines(source: string): string[] {
  const lines = source.split("\n");
  const out: string[] = [];
  let depth = 0;
  for (const line of lines) {
    if (line.includes("<Card>")) depth += 1;
    if (depth === 0) out.push(line);
    if (line.includes("</Card>")) depth = Math.max(0, depth - 1);
  }
  return out;
}

describe("Super Admin payouts page", () => {
  it("uses gradient ink for everything outside a card", () => {
    const offenders = gradientLevelLines(readFileSync(PAGE, "utf8"))
      .filter((line) => !line.trim().startsWith("//") && !line.trim().startsWith("*"))
      .filter((line) => /className=/.test(line))
      .filter((line) => /text-on-background|text-on-surface-variant/.test(line))
      .map((line) => line.trim());

    expect(
      offenders,
      "these sit on the gradient, where on-background resolves to panel ink and renders " +
        "at about 1.07:1 — use on-gradient / on-gradient-muted",
    ).toEqual([]);
  });

  it("still uses panel ink inside the card, where it belongs", () => {
    // The other half of the rule. If this ever goes away the fix above
    // was applied too broadly, and the card's text would be white on a
    // pale panel.
    const source = readFileSync(PAGE, "utf8");
    const card = source.slice(source.indexOf("<Card>"), source.indexOf("</Card>"));
    expect(card).toContain("text-on-surface-variant");
  });
});
