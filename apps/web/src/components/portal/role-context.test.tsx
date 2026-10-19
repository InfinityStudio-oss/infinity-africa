import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UserRole } from "@/lib/portal/roles";

import { RoleProvider, useRole } from "./role-context";

/**
 * Reported from production on 2026-10-19:
 *
 *   SecurityError: Failed to read the 'localStorage' property from
 *   'Window': Access is denied for this document.
 *
 * The browser refuses the property outright when site data is blocked,
 * in some private-browsing modes, and inside an iframe without
 * third-party storage access - the access throws rather than returning
 * null.
 *
 * RoleProvider wraps portal-shell, so it mounts on every merchant portal
 * page, and the throw was in a useEffect with no route-level error
 * boundary above it. React escalated it to app/global-error.tsx, which
 * replaces the whole page. A merchant with strict privacy settings got
 * an error screen instead of their portal, over a remembered navigation
 * preference.
 */

function Probe() {
  const { role, setRole } = useRole();
  return (
    <>
      <span data-testid="role">{role}</span>
      <button onClick={() => setRole(UserRole.MERCHANT_STAFF)}>switch</button>
    </>
  );
}

function denyStorage() {
  vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
    throw new DOMException("Access is denied for this document.", "SecurityError");
  });
  vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
    throw new DOMException("Access is denied for this document.", "SecurityError");
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("RoleProvider when the browser denies localStorage", () => {
  it("still renders the portal instead of throwing", () => {
    denyStorage();

    expect(() =>
      render(
        <RoleProvider>
          <Probe />
        </RoleProvider>,
      ),
    ).not.toThrow();

    expect(screen.getByTestId("role")).toBeInTheDocument();
  });

  it("falls back to the default role, which is what a first visit gets anyway", () => {
    denyStorage();

    render(
      <RoleProvider>
        <Probe />
      </RoleProvider>,
    );

    expect(screen.getByTestId("role")).toHaveTextContent(UserRole.MERCHANT_ADMIN);
  });

  it("still lets the merchant switch role for this session", () => {
    denyStorage();
    render(
      <RoleProvider>
        <Probe />
      </RoleProvider>,
    );

    fireEvent.click(screen.getByText("switch"));

    // Not remembered next visit, but the switch itself must work - the
    // write failing is not a reason for the click to do nothing.
    expect(screen.getByTestId("role")).toHaveTextContent(UserRole.MERCHANT_STAFF);
  });
});

describe("RoleProvider when localStorage works", () => {
  it("restores a previously chosen role", () => {
    window.localStorage.setItem("infinity_portal_role", UserRole.MERCHANT_STAFF);

    render(
      <RoleProvider>
        <Probe />
      </RoleProvider>,
    );

    expect(screen.getByTestId("role")).toHaveTextContent(UserRole.MERCHANT_STAFF);
  });

  it("remembers a switch", () => {
    render(
      <RoleProvider>
        <Probe />
      </RoleProvider>,
    );

    fireEvent.click(screen.getByText("switch"));

    expect(window.localStorage.getItem("infinity_portal_role")).toBe(UserRole.MERCHANT_STAFF);
  });

  it("ignores a stored value that is not a real role", () => {
    window.localStorage.setItem("infinity_portal_role", "SUPER_USER_PLEASE");

    render(
      <RoleProvider>
        <Probe />
      </RoleProvider>,
    );

    expect(screen.getByTestId("role")).toHaveTextContent(UserRole.MERCHANT_ADMIN);
  });
});
