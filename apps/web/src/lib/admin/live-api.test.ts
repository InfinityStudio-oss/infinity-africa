import { beforeEach, describe, expect, it, vi } from "vitest";

// live-api.ts is marked `import "server-only"`, which throws outside a
// real RSC build.
vi.mock("server-only", () => ({}));
vi.mock("@/lib/supabase/session", () => ({ getAccessToken: async () => "test-token" }));

/** A list endpoint holding `total` rows, served 100 at a time, exactly as
 * the API does (app/core/pagination.py caps page_size at 100). */
function listOf(total: number) {
  const calls: string[] = [];
  const fetchMock = vi.fn(async (url: string) => {
    calls.push(url);
    const query = new URLSearchParams(url.split("?")[1] ?? "");
    const size = Number(query.get("page_size") ?? 20);
    const page = Number(query.get("page") ?? 1);
    const start = (page - 1) * size;
    const rows = Array.from({ length: Math.max(0, Math.min(size, total - start)) }, (_, i) => ({
      merchant_id: String(start + i + 1),
    }));
    return {
      ok: true,
      json: async () => ({
        success: true,
        data: rows,
        meta: { page, page_size: size, total, total_pages: Math.ceil(total / size) },
      }),
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

describe("admin lists that must be complete on screen", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("returns every business, not just the first hundred", async () => {
    // The bug this exists for. The page asked for one page of 100 and
    // rendered whatever came back, so at 104 merchants four businesses
    // were unreachable — including the operator's own account. Nothing
    // said so: no pagination control, no "showing 100 of 104".
    const { calls } = listOf(104);
    const { listAdminMerchants } = await import("./live-api");

    const merchants = await listAdminMerchants();

    expect(merchants).toHaveLength(104);
    expect(calls).toHaveLength(2);
    expect(new Set(merchants.map((m) => m.merchant_id)).size).toBe(104);
  });

  it("costs one request when everything fits on one page", async () => {
    const { calls } = listOf(42);
    const { listAdminMerchants } = await import("./live-api");

    expect(await listAdminMerchants()).toHaveLength(42);
    expect(calls).toHaveLength(1);
  });

  it("keeps the caller's filters on every page it fetches", async () => {
    const { calls } = listOf(150);
    const { listAdminApiKeys } = await import("./live-api");

    await listAdminApiKeys({ environment: "live" });

    expect(calls).toHaveLength(2);
    for (const url of calls) {
      expect(url).toContain("environment=live");
    }
    expect(calls[0]).toContain("page=1");
    expect(calls[1]).toContain("page=2");
  });

  it("stops rather than spinning when a list shrinks mid-read", async () => {
    // total_pages says there is more; the next page comes back empty
    // because rows were removed between requests. Trusting the stale
    // count alone would fetch twenty empty pages.
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        const page = Number(new URLSearchParams(url.split("?")[1] ?? "").get("page") ?? 1);
        return {
          ok: true,
          json: async () => ({
            success: true,
            data: page === 1 ? [{ merchant_id: "1" }] : [],
            meta: { page, page_size: 100, total: 900, total_pages: 9 },
          }),
        };
      }),
    );
    const { listAdminMerchants } = await import("./live-api");

    expect(await listAdminMerchants()).toHaveLength(1);
    expect(calls).toHaveLength(2);
  });

  it("gives back an empty list, not an exception, when the read fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => ({ success: false }) })));
    const { listAdminMerchants } = await import("./live-api");

    await expect(listAdminMerchants()).resolves.toEqual([]);
  });

  it("still reads only the first page of the lists too large to load whole", async () => {
    // The audit log and the webhook queue are in the tens of thousands.
    // Loading them completely would be the wrong fix, so they are capped
    // on purpose — this pins that it stays a decision, not a regression.
    const { calls } = listOf(63745);
    const { listAdminAuditLogs } = await import("./live-api");

    expect(await listAdminAuditLogs()).toHaveLength(100);
    expect(calls).toHaveLength(1);
  });
});
