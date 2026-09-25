import { afterEach, describe, expect, it, vi } from "vitest";

// current-user.ts and its imports are marked `import "server-only"`, which
// throws outside a real RSC build.
vi.mock("server-only", () => ({}));

const getSession = vi.fn();
vi.mock("@/lib/supabase/session", () => ({ getSession: () => getSession() }));

const getMockSession = vi.fn();
vi.mock("./mock-session", () => ({ getMockSession: () => getMockSession() }));

const findById = vi.fn();
vi.mock("./mock-store", () => ({ findById: (id: string) => findById(id) }));

function setNodeEnv(value: string) {
  // stubEnv, not a direct assignment: NODE_ENV is a non-writable
  // property on process.env under vitest, and unstubbing restores it
  // even if an assertion throws midway.
  vi.stubEnv("NODE_ENV", value);
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  vi.resetModules();
});

describe("mock auth fallback", () => {
  it("is refused in production even with a valid mock cookie and a matching user", async () => {
    // The forged-cookie case: the mock session cookie is an unsigned user
    // id, so this is what an attacker gets to control directly.
    setNodeEnv("production");
    getSession.mockResolvedValue(null);
    getMockSession.mockResolvedValue("some-mock-user-id");
    findById.mockReturnValue({
      id: "some-mock-user-id",
      email: "attacker@example.com",
      fullName: "Attacker",
      phone: "",
    });

    const { getCurrentUser } = await import("./current-user");

    expect(await getCurrentUser()).toBeNull();
  });

  it("does not even consult the mock store in production", async () => {
    setNodeEnv("production");
    getSession.mockResolvedValue(null);
    getMockSession.mockResolvedValue("some-mock-user-id");

    const { getCurrentUser } = await import("./current-user");
    await getCurrentUser();

    expect(findById).not.toHaveBeenCalled();
  });

  it("still resolves a real Supabase session in production", async () => {
    // The gate must close the fallback only — a genuine session is
    // unaffected.
    setNodeEnv("production");
    getSession.mockResolvedValue({
      user: { id: "real-user", email: "owner@example.com", user_metadata: { full_name: "Owner" } },
    });

    const { getCurrentUser } = await import("./current-user");
    const user = await getCurrentUser();

    expect(user).toMatchObject({ id: "real-user", email: "owner@example.com", source: "supabase" });
  });

  it("remains available outside production, where it exists for offline development", async () => {
    setNodeEnv("development");
    getSession.mockResolvedValue(null);
    getMockSession.mockResolvedValue("dev-user");
    findById.mockReturnValue({
      id: "dev-user",
      email: "dev@example.com",
      fullName: "Dev",
      phone: "",
    });

    const { getCurrentUser } = await import("./current-user");
    const user = await getCurrentUser();

    expect(user).toMatchObject({ id: "dev-user", source: "mock" });
  });
});
