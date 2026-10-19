"use client";

import { createContext, useContext, useEffect, useState } from "react";

import { UserRole } from "@/lib/portal/roles";

const STORAGE_KEY = "infinity_portal_role";
const DEFAULT_ROLE = UserRole.MERCHANT_ADMIN;

interface RoleContextValue {
  role: UserRole;
  setRole: (role: UserRole) => void;
}

const RoleContext = createContext<RoleContextValue>({
  role: DEFAULT_ROLE,
  setRole: () => {},
});

/**
 * Reading localStorage can throw, and did.
 *
 * `SecurityError: Access is denied for this document` was reported from
 * production on 2026-10-19. The browser refuses the property entirely
 * when site data is blocked, in some private-browsing modes, and inside
 * an iframe without third-party storage access - the access throws
 * rather than returning null.
 *
 * That mattered here more than it looks. RoleProvider wraps portal-shell,
 * so it is mounted on every merchant portal page, and the throw happened
 * in a useEffect with no route-level error boundary above it. React
 * escalated it to app/global-error.tsx, which replaces the whole page -
 * so a merchant with strict privacy settings got an error screen instead
 * of their portal, over a remembered nav preference.
 *
 * Failing soft costs nothing here: the fallback is DEFAULT_ROLE, which
 * is exactly what a first-time visitor gets. The role only decides which
 * navigation is shown; every actual permission is enforced by the
 * backend, so a browser that cannot remember this preference loses a
 * convenience and nothing else.
 */
function readStoredRole(): UserRole | null {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored && Object.values(UserRole).includes(stored as UserRole)
      ? (stored as UserRole)
      : null;
  } catch {
    return null;
  }
}

function writeStoredRole(role: UserRole): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, role);
  } catch {
    // The switch still works for this session; it just will not be
    // remembered. Silent on purpose - a merchant who has deliberately
    // blocked site data does not need telling about it every time they
    // change a view.
  }
}

export function RoleProvider({ children }: { children: React.ReactNode }) {
  const [role, setRoleState] = useState<UserRole>(DEFAULT_ROLE);

  useEffect(() => {
    const stored = readStoredRole();
    if (stored) {
      // Deliberately a post-mount sync, not a derivable-from-props value: the
      // stored role is only knowable client-side (SSR has no localStorage),
      // so a lazy useState initializer would desync from the server-rendered
      // default and produce a hydration mismatch in role-gated UI below.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRoleState(stored);
    }
  }, []);

  const setRole = (next: UserRole) => {
    setRoleState(next);
    writeStoredRole(next);
  };

  return <RoleContext.Provider value={{ role, setRole }}>{children}</RoleContext.Provider>;
}

export function useRole() {
  return useContext(RoleContext);
}
