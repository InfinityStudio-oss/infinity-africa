import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { getSuperAdminMfaState, superAdminMfaRequired } from "./super-admin-mfa";

afterEach(() => {
  vi.unstubAllEnvs();
});

function supabaseWith({
  currentLevel,
  totp = [],
  throws = false,
}: {
  currentLevel?: string | null;
  totp?: Array<{ id: string; status: string }>;
  throws?: boolean;
}) {
  return {
    auth: {
      mfa: {
        getAuthenticatorAssuranceLevel: async () => {
          if (throws) throw new Error("network");
          return { data: { currentLevel } };
        },
        listFactors: async () => ({ data: { totp } }),
      },
    },
  };
}

describe("superAdminMfaRequired", () => {
  it("is off unless explicitly set to true", () => {
    vi.stubEnv("REQUIRE_SUPER_ADMIN_MFA", "");
    expect(superAdminMfaRequired()).toBe(false);
  });

  it("does not treat other truthy-looking values as on", () => {
    // Guards against a "1" or "yes" in Railway being read as enabled —
    // or, worse, being assumed enabled when it is not.
    vi.stubEnv("REQUIRE_SUPER_ADMIN_MFA", "1");
    expect(superAdminMfaRequired()).toBe(false);
  });

  it("is on for exactly 'true'", () => {
    vi.stubEnv("REQUIRE_SUPER_ADMIN_MFA", "true");
    expect(superAdminMfaRequired()).toBe(true);
  });
});

describe("getSuperAdminMfaState", () => {
  it("is satisfied once the session itself reached aal2", async () => {
    expect(await getSuperAdminMfaState(supabaseWith({ currentLevel: "aal2" }))).toBe("satisfied");
  });

  it("needs enrollment when no verified factor exists", async () => {
    expect(await getSuperAdminMfaState(supabaseWith({ currentLevel: "aal1", totp: [] }))).toBe(
      "needs-enrollment",
    );
  });

  it("ignores an unverified factor left over from an abandoned setup", async () => {
    const state = await getSuperAdminMfaState(
      supabaseWith({ currentLevel: "aal1", totp: [{ id: "f1", status: "unverified" }] }),
    );
    expect(state).toBe("needs-enrollment");
  });

  it("needs verification when a factor exists but this session is only aal1", async () => {
    // Enrolment having happened is not the same as it having been used on
    // this session — the whole reason currentLevel is what we branch on.
    const state = await getSuperAdminMfaState(
      supabaseWith({ currentLevel: "aal1", totp: [{ id: "f1", status: "verified" }] }),
    );
    expect(state).toBe("needs-verification");
  });

  it("fails closed when Supabase cannot be reached", async () => {
    expect(await getSuperAdminMfaState(supabaseWith({ throws: true }))).toBe("needs-verification");
  });

  it("does not treat a missing assurance level as satisfied", async () => {
    const state = await getSuperAdminMfaState(
      supabaseWith({ currentLevel: null, totp: [{ id: "f1", status: "verified" }] }),
    );
    expect(state).toBe("needs-verification");
  });
});

describe("module boundaries", () => {
  it("does not import lib/supabase/protected-route", async () => {
    // A cycle between these two modules left one side undefined at runtime
    // and broke logout across both the merchant and Super Admin portals.
    // protected-route imports this module, so this one must not import back.
    const fs = await import("node:fs/promises");
    // vitest runs from apps/web, and import.meta.url is not a file URL
    // under the jsdom environment.
    const source = await fs.readFile("src/lib/auth/super-admin-mfa.ts", "utf8");
    expect(source).not.toMatch(/from\s+["'].*protected-route["']/);
  });
});
