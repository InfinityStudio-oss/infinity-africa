import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The Overview must not fetch merchant data on the server.
 *
 * lib/portal/api.ts signs every request with getAccessTokenClient(),
 * which is a "use client" module reading the BROWSER session. Called
 * from a Server Component it returns null, the request goes out with no
 * Authorization header, apps/api answers 401, and apiGet turns that into
 * null — which this page then read as "no data" and answered with the
 * first-run welcome screen.
 *
 * Every verified merchant saw that screen. Nothing errored, nothing
 * logged, and the production data was healthy, so it looked like an
 * undeployed redesign rather than a page that never had a token.
 *
 * These are source assertions rather than render assertions on purpose:
 * the failure is in *where* the call happens, which no amount of
 * rendering the component in jsdom can reproduce.
 */

const PAGE = join(process.cwd(), "src/app/dashboard/overview/page.tsx");
const source = readFileSync(PAGE, "utf8");

describe("the Overview page", () => {
  it("is a Server Component, so it must not import the client-only data layer", () => {
    expect(source).not.toMatch(/from "@\/lib\/portal\/api"/);
  });

  it("does not call any merchant data fetcher itself", () => {
    for (const fetcher of [
      "getMerchantOverview",
      "readMerchantOverview",
      "getOverviewReport",
      "getPayoutWallet",
    ]) {
      expect(source).not.toContain(fetcher);
    }
  });

  it("still guards access before rendering anything", () => {
    // The dashboard renders unconditionally now, so these two are the
    // only things standing between a stranger and the shell.
    expect(source).toContain("requireCurrentUser");
    expect(source).toContain("redirectIfSuspended");
  });

  it("never branches between two different pages on a fetch result", () => {
    // The specific shape of the bug: `overview ? <Dashboard/> :
    // <Welcome/>`, where the left side is null for both "no data" and
    // "the request failed".
    expect(source).not.toContain("OverviewWelcome");
  });

  it("renders the dashboard", () => {
    expect(source).toContain("<OverviewDashboard />");
  });
});

describe("the Overview dashboard component", () => {
  const DASHBOARD = join(process.cwd(), "src/components/merchant/overview-dashboard.tsx");
  const dashboard = readFileSync(DASHBOARD, "utf8");

  it("is a Client Component, which is what makes its token work", () => {
    expect(dashboard.trimStart().startsWith('"use client"')).toBe(true);
  });

  it("fetches the merchant and the wallet itself", () => {
    expect(dashboard).toContain("readMerchantOverview");
    expect(dashboard).toContain("getPayoutWallet");
  });

  it("starts in a loading state rather than an empty one", () => {
    // Before the first response lands there is no data, and rendering
    // zeros for that is a fake zero with a timer on it — a merchant who
    // glances at the page mid-load sees "TZS 0.00" takings.
    expect(dashboard).toContain("useState(true)");
  });
});
