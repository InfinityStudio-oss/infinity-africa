import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

// redirect() throws in Next so control never returns past it; this mirrors
// that, and the thrown value tells us where it sent the caller.
class RedirectError extends Error {
  constructor(public readonly to: string) {
    super(`redirect:${to}`);
  }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new RedirectError(to);
  },
}));

const requireUser = vi.fn();
vi.mock("@/lib/supabase/protected-route", () => ({
  requireUser: (...args: unknown[]) => requireUser(...args),
}));

import {
  getSuperAdminMfaState,
  requireSuperAdminIdentity,
  superAdminMfaRequired,
} from "./super-admin-mfa";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function supabaseWith({
  admin,
  currentLevel,
  totp = [],
  throws = false,
}: {
  admin?: boolean;
  currentLevel?: string | null;
  totp?: Array<{ id: string; status: string }>;
  throws?: boolean;
}) {
  return {
    from: () => ({
      select: () => ({
        eq: () => ({ maybeSingle: async () => ({ data: admin ? { id: "row" } : null }) }),
      }),
    }),
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
    // Guards against a "1" or "yes" in Railway silently enabling
    // enforcement, or worse, silently not enabling it.
    vi.stubEnv("REQUIRE_SUPER_ADMIN_MFA", "1");
    expect(superAdminMfaRequired()).toBe(false);
  });

  it("is on for exactly 'true'", () => {
    vi.stubEnv("REQUIRE_SUPER_ADMIN_MFA", "true");
    expect(superAdminMfaRequired()).toBe(true);
  });
});

describe("requireSuperAdminIdentity", () => {
  it("sends a signed-out visitor to the admin login", async () => {
    requireUser.mockImplementation((to: string) => {
      throw new RedirectError(to);
    });

    await expect(requireSuperAdminIdentity()).rejects.toThrow("redirect:/admin-login");
  });

  it("turns a merchant away from the MFA pages", async () => {
    // The MFA pages must not become an authenticated-but-unguarded corner
    // of the app just because they skip the MFA gate.
    requireUser.mockResolvedValue({ user: { id: "u1" }, supabase: supabaseWith({ admin: false }) });

    await expect(requireSuperAdminIdentity()).rejects.toThrow("redirect:/portal");
  });

  it("lets a platform admin through without requiring a second factor yet", async () => {
    requireUser.mockResolvedValue({ user: { id: "u1" }, supabase: supabaseWith({ admin: true }) });

    await expect(requireSuperAdminIdentity()).resolves.toMatchObject({ user: { id: "u1" } });
  });
});

describe("getSuperAdminMfaState", () => {
  it("is satisfied once the session itself reached aal2", async () => {
    const state = await getSuperAdminMfaState(
      supabaseWith({ currentLevel: "aal2" }) as never,
    );
    expect(state).toBe("satisfied");
  });

  it("needs enrollment when no verified factor exists", async () => {
    const state = await getSuperAdminMfaState(
      supabaseWith({ currentLevel: "aal1", totp: [] }) as never,
    );
    expect(state).toBe("needs-enrollment");
  });

  it("ignores an unverified factor left over from an abandoned setup", async () => {
    const state = await getSuperAdminMfaState(
      supabaseWith({ currentLevel: "aal1", totp: [{ id: "f1", status: "unverified" }] }) as never,
    );
    expect(state).toBe("needs-enrollment");
  });

  it("needs verification when a factor exists but this session is only aal1", async () => {
    // Enrolment having happened is not the same as it having been used on
    // this session — the whole point of checking currentLevel.
    const state = await getSuperAdminMfaState(
      supabaseWith({ currentLevel: "aal1", totp: [{ id: "f1", status: "verified" }] }) as never,
    );
    expect(state).toBe("needs-verification");
  });

  it("fails closed when Supabase cannot be reached", async () => {
    const state = await getSuperAdminMfaState(supabaseWith({ throws: true }) as never);
    expect(state).toBe("needs-verification");
  });

  it("does not treat a missing assurance level as satisfied", async () => {
    const state = await getSuperAdminMfaState(
      supabaseWith({ currentLevel: null, totp: [{ id: "f1", status: "verified" }] }) as never,
    );
    expect(state).toBe("needs-verification");
  });
});
