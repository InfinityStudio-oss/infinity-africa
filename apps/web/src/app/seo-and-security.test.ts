/**
 * MVP security/SEO hardening pass — covers:
 *  - robots.ts / sitemap.ts (imported and called directly; no Next runtime needed)
 *  - next.config.ts's security headers (imported directly; `headers()` is a
 *    plain async function, no Next runtime needed either)
 *  - every private-route-group layout's `robots: { index: false }` metadata,
 *    plus root layout.tsx's Open Graph/Twitter image — read as raw source
 *    via node:fs rather than imported, since layout.tsx pulls in
 *    next/font/google (a build-time-only SWC transform apps/web's own
 *    next.config.ts/vitest setup doesn't provide outside a real Next build)
 *    and the three route-group layouts (portal/admin/super-admin) pull in
 *    real Supabase/session code not worth mocking just to read a metadata
 *    object two lines away.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import robots from "./robots";
import sitemap from "./sitemap";

const appDir = dirname(fileURLToPath(import.meta.url));

function source(relativePath: string): string {
  return readFileSync(join(appDir, relativePath), "utf8");
}

describe("robots.ts", () => {
  it("allows public marketing pages and blocks every private/auth/transaction route", () => {
    const result = robots();
    const rules = Array.isArray(result.rules) ? result.rules[0] : result.rules;
    expect(rules.allow).toBe("/");
    const disallow = rules.disallow as string[];
    for (const path of [
      "/dashboard",
      "/portal",
      "/super-admin",
      "/admin",
      "/admin-login",
      "/login",
      "/onboarding",
      "/pay",
      "/payment-links",
      "/invoices",
      "/api",
      "/v1",
    ]) {
      expect(disallow).toContain(path);
    }
  });

  it("points at the production sitemap", () => {
    expect(robots().sitemap).toBe("https://infinitypay.me/sitemap.xml");
  });
});

describe("sitemap.ts", () => {
  const entries = sitemap();
  const urls = entries.map((entry) => entry.url);

  it("includes the homepage and public marketing/developer-docs pages", () => {
    expect(urls).toContain("https://infinitypay.me/");
    expect(urls).toContain("https://infinitypay.me/solutions");
    expect(urls).toContain("https://infinitypay.me/developers");
    expect(urls).toContain("https://infinitypay.me/developers/webhooks");
  });

  it("never includes a private, authenticated, or transaction-specific path", () => {
    // Checked against the URL's first path segment only — "/developers/
    // payment-links" (a legitimate public docs page *about* payment links)
    // must not be flagged just because "payment-links" appears somewhere
    // in the path; only the actual private route "/payment-links/..." itself
    // (first segment) is disallowed.
    const privateFirstSegments = new Set([
      "dashboard",
      "merchant",
      "portal",
      "super-admin",
      "admin",
      "admin-login",
      "onboarding",
      "pay",
      "payment-links",
      "invoices",
      "login",
    ]);
    for (const url of urls) {
      const firstSegment = new URL(url).pathname.split("/").filter(Boolean)[0];
      expect(privateFirstSegments.has(firstSegment)).toBe(false);
    }
  });

  it("gives every URL an absolute https://infinitypay.me origin", () => {
    for (const url of urls) {
      expect(url.startsWith("https://infinitypay.me")).toBe(true);
    }
  });
});

describe("next.config.ts security headers", () => {
  it("sends the standard defensive header set on every route", async () => {
    const { default: nextConfig } = await import("../../next.config");
    const rules = await nextConfig.headers!();
    expect(rules).toHaveLength(1);
    expect(rules[0].source).toBe("/(.*)");
    const byKey = Object.fromEntries(rules[0].headers.map((h) => [h.key, h.value]));
    expect(byKey["X-Content-Type-Options"]).toBe("nosniff");
    expect(byKey["X-Frame-Options"]).toBe("DENY");
    expect(byKey["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(byKey["Strict-Transport-Security"]).toContain("max-age=63072000");
    expect(byKey["Cross-Origin-Opener-Policy"]).toBe("same-origin");
    expect(byKey["Cross-Origin-Resource-Policy"]).toBe("same-origin");
    expect(byKey["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
  });
});

describe("root layout.tsx metadata", () => {
  const layoutSource = source("layout.tsx");

  it("uses the versioned v1 Open Graph/Twitter image at the recommended absolute URL", () => {
    expect(layoutSource).toContain("https://infinitypay.me/og/infinitypay-og-v1.png");
  });

  it("never references the old logo file in social metadata", () => {
    expect(layoutSource).not.toMatch(/openGraph[\s\S]*infinity-logo-v2\.png/);
    expect(layoutSource).not.toMatch(/twitter[\s\S]*infinity-logo-v2\.png/);
    // The only mention anywhere in the file, if any, must be a code comment
    // explaining the old-vs-new distinction — never an actual image path.
    for (const line of layoutSource.split("\n")) {
      if (line.includes("infinity-logo-v2.png")) {
        expect(line.trim().startsWith("//") || line.trim().startsWith("*")).toBe(true);
      }
    }
  });

  it("sets a summary_large_image Twitter card", () => {
    expect(layoutSource).toMatch(/card:\s*"summary_large_image"/);
  });

  it("declares a canonical URL", () => {
    expect(layoutSource).toContain("https://infinitypay.me/");
    expect(layoutSource).toMatch(/canonical:/);
  });
});

describe("Material Symbols icon font loading", () => {
  // Regression cover for raw ligature names ("smartphone",
  // "account_balance_wallet", "qr_code_scanner") rendering as readable text
  // over the UI on a hard refresh. The glyph IS the span's text content, so
  // the fix is entirely about never painting that text.
  const layoutSource = readFileSync(join(appDir, "layout.tsx"), "utf8");
  const globalsSource = readFileSync(join(appDir, "globals.css"), "utf8");

  it("requests the icon font with display=block, never display=swap", () => {
    // swap paints the fallback immediately; for an icon font that means
    // showing the ligature's own name until the real font arrives.
    expect(layoutSource).toContain("display=block");
    expect(layoutSource).not.toContain("Outlined:wght,FILL@100..700,0..1&display=swap");
  });

  it("marks icons pending inline, before the first paint", () => {
    // Anything deferred runs after the frame this is meant to cover.
    expect(layoutSource).toContain("icons-pending");
    expect(layoutSource).toContain("dangerouslySetInnerHTML");
  });

  it("releases the pending guard even if the font never loads", () => {
    // Otherwise a blocked font would leave every icon permanently invisible.
    expect(layoutSource).toContain("setTimeout(show,3000)");
  });

  it("declares the icon font-family locally, not only via Google's stylesheet", () => {
    // That remote stylesheet is what defines the class — until it arrives the
    // span has no icon font at all and renders its ligature as plain words.
    expect(globalsSource).toContain('font-family: "Material Symbols Outlined"');
    expect(globalsSource).toContain(".icons-pending .material-symbols-outlined");
  });
});

describe("private route groups are noindex", () => {
  const privateLayoutFiles = [
    "portal/layout.tsx",
    "admin/layout.tsx",
    "super-admin/layout.tsx",
    "dashboard/layout.tsx",
    "onboarding/layout.tsx",
    "pay/layout.tsx",
    "payment-links/layout.tsx",
    "invoices/layout.tsx",
    "login/layout.tsx",
    "admin-login/layout.tsx",
  ];

  it.each(privateLayoutFiles)("%s sets robots: { index: false, follow: false }", (relativePath) => {
    const layoutSource = source(relativePath);
    expect(layoutSource).toMatch(/robots:\s*{\s*index:\s*false,\s*follow:\s*false\s*}/);
  });
});
