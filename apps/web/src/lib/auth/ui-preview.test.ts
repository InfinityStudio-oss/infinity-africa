import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { uiPreviewEnabled } from "./ui-preview";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("__PORTAL_UI_PREVIEW__", () => {
  it("is refused in production", async () => {
    // Where this flag is honoured it skips requireSuperAdmin() entirely,
    // so honouring it in production would expose the whole Super Admin
    // console to anyone.
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("__PORTAL_UI_PREVIEW__", "1");

    expect(uiPreviewEnabled()).toBe(false);
  });

  it("is available in development, which is what it exists for", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("__PORTAL_UI_PREVIEW__", "1");

    expect(uiPreviewEnabled()).toBe(true);
  });

  it("stays off when the flag is absent", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("__PORTAL_UI_PREVIEW__", "");

    expect(uiPreviewEnabled()).toBe(false);
  });
});
