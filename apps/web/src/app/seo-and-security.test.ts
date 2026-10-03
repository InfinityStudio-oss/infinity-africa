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
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import robots from "./robots";
import sitemap from "./sitemap";

const appDir = dirname(fileURLToPath(import.meta.url));

/** Source with comments stripped.
 *
 * Several of these assertions are "this must NOT appear", and the files
 * legitimately discuss the very things being excluded — structured-data.tsx
 * explains why it omits `sameAs`, for instance. Matching raw source would
 * fail on the explanation rather than on the code.
 */
function code(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !line.trim().startsWith("//") && !line.trim().startsWith("*"))
    .join("\n");
}

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

describe("next.config.ts monitoring origins in the CSP", () => {
  /**
   * connect-src is `'self'` plus Supabase and the API, so Sentry and
   * PostHog — which report by POSTing to their own hosts — are blocked
   * unless their origin is added. The failure mode is quiet: the SDKs
   * initialise, look healthy, and have every event dropped by the
   * browser. These tests are what stop that shipping.
   *
   * next.config.ts reads process.env once at module load, so each case
   * resets the module registry to get a fresh evaluation.
   */
  async function connectSrc(): Promise<string> {
    vi.resetModules();
    const { default: nextConfig } = await import("../../next.config");
    const rules = await nextConfig.headers!();
    const csp = rules[0].headers.find((h) => h.key === "Content-Security-Policy")!.value;
    return csp.split("; ").find((directive) => directive.startsWith("connect-src"))!;
  }

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("stays narrow when monitoring is not configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "");
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "");
    const directive = await connectSrc();
    expect(directive).not.toContain("sentry.io");
    expect(directive).not.toContain("posthog.com");
  });

  it("allows Sentry's ingest origin when a DSN is configured, and never leaks the key", async () => {
    vi.stubEnv(
      "NEXT_PUBLIC_SENTRY_DSN",
      "https://examplepublickey@o4500000000000000.ingest.de.sentry.io/4500000000000001",
    );
    const directive = await connectSrc();
    expect(directive).toContain("https://o4500000000000000.ingest.de.sentry.io");
    // Only the origin is taken. The DSN's public key must not end up in a
    // response header on every page.
    expect(directive).not.toContain("examplepublickey");
  });

  it("allows PostHog's host when a key is configured, and never leaks the key", async () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "phc_example");
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_HOST", "https://eu.i.posthog.com");
    const directive = await connectSrc();
    expect(directive).toContain("https://eu.i.posthog.com");
    expect(directive).not.toContain("phc_");
  });

  it("leaves the policy alone rather than breaking the build on a malformed DSN", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "not-a-url");
    const directive = await connectSrc();
    expect(directive).toContain("'self'");
    expect(directive).not.toContain("not-a-url");
  });
});

describe("root layout.tsx metadata", () => {
  const layoutSource = source("layout.tsx");

  it("uses the versioned v1 Open Graph/Twitter image at the recommended absolute URL", () => {
    expect(layoutSource).toContain("https://infinitypay.me/og/infinitypay-og-v2.png");
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

  it("declares metadataBase as the official domain", () => {
    expect(layoutSource).toMatch(/metadataBase:\s*new URL\("https:\/\/infinitypay\.me"\)/);
  });

  it("does NOT declare a canonical of its own", () => {
    // The bug this replaced: Next merges metadata down the tree, so a
    // canonical on the root layout was inherited by every page that did not
    // override it. /solutions, /contact and all 14 developer-docs pages
    // shipped `<link rel="canonical" href="https://infinitypay.me">`,
    // telling Google they were duplicates of the homepage. Each public page
    // now declares its own; the homepage's lives in app/page.tsx.
    expect(code(layoutSource)).not.toMatch(/canonical/);
  });

  it("suffixes child page titles with the country, not the bare brand", () => {
    // "InfinityPay" alone is used by several unrelated companies, which is
    // the whole reason this site is hard to find.
    expect(layoutSource).toMatch(/template:\s*"%s \| InfinityPay Tanzania"/);
  });

  it("supports Google Search Console verification from the environment", () => {
    expect(layoutSource).toContain("NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION");
    // Never a committed token.
    expect(layoutSource).not.toMatch(/google:\s*"[A-Za-z0-9_-]{20,}"/);
  });

  it("never points public metadata at localhost or a preview domain", () => {
    expect(layoutSource).not.toMatch(/localhost/);
    expect(layoutSource).not.toMatch(/vercel\.app/);
  });
});

describe("per-page canonical URLs", () => {
  // The guard against the inherited-canonical bug coming back: every page
  // the sitemap offers Google must point at itself, not at anything else.
  const entries = sitemap();

  it("covers every sitemap entry with a self-referencing canonical", () => {
    const wrong: string[] = [];
    for (const entry of entries) {
      const path = new URL(entry.url).pathname;
      const file = path === "/" ? "page.tsx" : `${path.slice(1)}/page.tsx`;
      let pageSource: string;
      try {
        pageSource = source(file);
      } catch {
        wrong.push(`${path}: no page file at ${file}`);
        continue;
      }
      const expected = path === "/" ? 'canonical: "/"' : `canonical: "${path}"`;
      if (!pageSource.includes(expected)) {
        wrong.push(`${path}: expected ${expected}`);
      }
    }
    expect(wrong).toEqual([]);
  });

  it("never lets a non-homepage page canonicalise to the homepage", () => {
    const offenders = entries
      .map((entry) => new URL(entry.url).pathname)
      .filter((path) => path !== "/")
      .filter((path) => {
        const pageSource = source(`${path.slice(1)}/page.tsx`);
        return /canonical:\s*"(\/|https:\/\/infinitypay\.me\/?)"/.test(pageSource);
      });
    expect(offenders).toEqual([]);
  });

  it("does not offer a redirect-only page to Google", () => {
    // /get-started only redirects to /create-account, and a redirect in a
    // sitemap is reported as an error in Search Console.
    const paths = entries.map((entry) => new URL(entry.url).pathname);
    expect(paths).not.toContain("/get-started");
  });
});

describe("homepage structured data", () => {
  const structured = readFileSync(
    join(appDir, "..", "components", "marketing", "structured-data.tsx"),
    "utf8",
  );

  it("is rendered on the homepage", () => {
    expect(source("page.tsx")).toContain("<StructuredData />");
  });

  it("claims the official domain and the Tanzania-qualified names", () => {
    expect(structured).toContain("https://infinitypay.me");
    expect(structured).toContain("InfinityPay Tanzania");
    expect(structured).toContain("InfinityPay.me");
  });

  it("states the country, so the entity is distinguishable from the other InfinityPays", () => {
    expect(structured).toMatch(/addressCountry:\s*"TZ"/);
    expect(structured).toMatch(/name:\s*"Tanzania"/);
  });

  it("invents no social profiles", () => {
    // The brief is explicit: no fake sameAs links. A dead profile link is
    // worse for an entity claim than no link at all.
    expect(code(structured)).not.toMatch(/sameAs/);
  });

  it("declares no site-search action, because there is no site search", () => {
    expect(code(structured)).not.toMatch(/SearchAction/);
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
    expect(layoutSource).toMatch(/Date\.now\(\)-t0>\d+/);
    expect(layoutSource).toContain("return show()");
  });

  it("waits on document.fonts.check rather than the promise from load()", () => {
    // load() resolves with the faces that MATCHED, and this script runs
    // before the stylesheet below it has been parsed — so no face is
    // declared yet, nothing matches, and the promise resolves within a
    // frame. The guard was being dropped before the font existed, which
    // is exactly when the ligature names show.
    expect(layoutSource).toContain("document.fonts.check");
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

describe("documented hostnames", () => {
  // Two dead hosts shipped in the public docs: sandbox.infinitypay.me
  // (there is no separate sandbox host — the API key picks the
  // environment) and pay.infinitypay.me (payment links live at
  // infinitypay.me/pay/{slug}). Neither resolves, so an integrator
  // following the docs hits a DNS failure and reasonably concludes the
  // integration is broken.
  const REAL_HOSTS = new Set(["api.infinitypay.me", "infinitypay.me", "www.infinitypay.me"]);

  function docsSources(): Array<[string, string]> {
    const dir = join(appDir, "developers");
    const out: Array<[string, string]> = [];
    const walk = (current: string) => {
      for (const entry of readdirSync(current, { withFileTypes: true })) {
        const full = join(current, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith(".tsx")) out.push([full, readFileSync(full, "utf8")]);
      }
    };
    walk(dir);
    return out;
  }

  it("only advertises hostnames that actually exist", () => {
    const offenders: string[] = [];
    for (const [file, source] of docsSources()) {
      for (const match of source.matchAll(/https:\/\/([a-z0-9.-]*infinitypay\.me)/g)) {
        if (!REAL_HOSTS.has(match[1])) offenders.push(`${file}: ${match[1]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("does not claim a separate sandbox host", () => {
    // Sandbox is chosen by the key (sk_test_), against the same base URL.
    for (const [, source] of docsSources()) {
      expect(source).not.toMatch(/sandbox\.infinitypay\.me/);
    }
  });
});
