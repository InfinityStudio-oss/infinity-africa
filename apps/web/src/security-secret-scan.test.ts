/**
 * MVP security-hardening pass: a regression guard that no backend secret's
 * env-var name ever appears anywhere in the frontend source tree — the
 * architectural invariant this whole app relies on is that apps/web never
 * touches these at all (only apps/api's app/config/settings.py does); a
 * manual `rg` secret scan (see docs/MVP_LAUNCH_CHECKLIST.md) catches this
 * once per audit, this test catches it on every CI run.
 *
 * Named exactly (not generic substrings like "SECRET"/"TOKEN"/"PASSWORD")
 * to avoid false positives on this codebase's own legitimate camelCase
 * identifiers (accessToken, resetToken, ...) — a case-sensitive
 * SCREAMING_SNAKE_CASE env-var name is what an accidentally-hardcoded or
 * accidentally-referenced secret would actually look like, matching how
 * the brief's own `rg` patterns are written.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
const THIS_FILE = fileURLToPath(import.meta.url);

// Every real secret field in apps/api/app/config/settings.py, as the
// SCREAMING_SNAKE_CASE env-var name pydantic-settings resolves it to.
const FORBIDDEN_NAMES = [
  "RESEND_API_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "SUPABASE_JWT_SECRET",
  "DATABASE_URL",
  "SELCOM_WEBHOOK_SECRET",
  "WEBHOOK_SECRET_ENCRYPTION_KEY",
  "SELCOM_API_KEY",
  "SELCOM_API_SECRET",
  "SELCOM_VENDOR_ID",
  "SELCOM_BUSINESS_API_KEY",
  "SELCOM_BUSINESS_PRIVATE_KEY_BASE64",
  "SELCOM_BUSINESS_ACCOUNT_NUMBER",
  "SELCOM_CHECKOUT_API_KEY",
  "SELCOM_CHECKOUT_API_SECRET",
  "SELCOM_CHECKOUT_PRIVATE_KEY_BASE64",
  "SELCOM_CHECKOUT_WEBHOOK_TEST_SECRET",
  // Added 2026-10-20. The security inspection compared this list against
  // settings.py and found it had stopped keeping up: these two were added
  // to the backend on 2026-10-16/17 and nothing here knew about them. A
  // hand-maintained list of secrets silently stops covering the newest
  // ones, which are the ones most likely to be mishandled, so
  // scripts/security_daily_check.py now diffs the two and fails on the gap.
  "OASIS_SMS_API_KEY",
  "OASIS_SMS_WEBHOOK_SECRET",
  // Deliberately NOT listed, having checked what each one actually is:
  //
  //   SENTRY_DSN       already guarded, and more precisely, by
  //                    seo-and-security.test.ts, which asserts no client
  //                    bundle reads process.env.SENTRY_DSN. Listing it here
  //                    would also false-positive on NEXT_PUBLIC_SENTRY_DSN
  //                    (this scan matches by substring), which the browser
  //                    is *supposed* to ship - a Sentry DSN is public by
  //                    design and cannot read anything back out of Sentry.
  //   POSTHOG_API_KEY  a write-only project key, not a PostHog personal API
  //                    key. The privileged form (phx_/phs_/php_) is caught
  //                    by value in apps/api/tests/test_no_committed_secrets.py,
  //                    which is the right place for it.
];

function walk(dir: string, files: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, files);
    } else if (/\.(ts|tsx|js|jsx)$/.test(entry.name) && full !== THIS_FILE) {
      files.push(full);
    }
  }
  return files;
}

describe("no backend secret env-var name appears in the frontend source tree", () => {
  const files = walk(SRC_DIR);

  it("scans a non-trivial number of frontend source files", () => {
    // Sanity check on the scan itself — a walker that silently found
    // nothing would make every assertion below vacuously true.
    expect(files.length).toBeGreaterThan(50);
  });

  it.each(FORBIDDEN_NAMES)("%s never appears in apps/web/src", (name) => {
    const offenders = files.filter((file) => readFileSync(file, "utf8").includes(name));
    expect(offenders).toEqual([]);
  });

  it("never defines a NEXT_PUBLIC_ variant of any backend secret", () => {
    const offenders: string[] = [];
    for (const file of files) {
      const content = readFileSync(file, "utf8");
      for (const name of FORBIDDEN_NAMES) {
        if (content.includes(`NEXT_PUBLIC_${name}`)) offenders.push(`${file}: NEXT_PUBLIC_${name}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
