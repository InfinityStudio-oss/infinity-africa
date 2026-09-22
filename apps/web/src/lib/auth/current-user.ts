import "server-only";

import { redirect } from "next/navigation";

import { getSession } from "@/lib/supabase/session";

import { findById } from "./mock-store";
import { getMockSession } from "./mock-session";

export interface CurrentUser {
  id: string;
  email: string;
  fullName: string;
  phone: string;
  source: "supabase" | "mock";
}

/**
 * The signed-in merchant, regardless of whether they authenticated through
 * real Supabase Auth or the mock fallback store. This is the single
 * abstraction the new merchant auth/onboarding flow uses for guards and
 * actions — it deliberately does not touch lib/supabase/protected-route.ts,
 * which stays pure-Supabase for /admin/*.
 */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const session = await getSession();
  if (session) {
    const { user } = session;
    const meta = (user.user_metadata ?? {}) as Record<string, unknown>;
    return {
      id: user.id,
      email: user.email ?? "",
      fullName: typeof meta.full_name === "string" ? meta.full_name : "",
      phone: typeof meta.phone === "string" ? meta.phone : "",
      source: "supabase",
    };
  }

  const mockUserId = await getMockSession();
  if (mockUserId) {
    const mockUser = findById(mockUserId);
    if (mockUser) {
      return {
        id: mockUser.id,
        email: mockUser.email,
        fullName: mockUser.fullName,
        phone: mockUser.phone,
        source: "mock",
      };
    }
  }

  return null;
}

export async function requireCurrentUser(redirectTo = "/dashboard/login"): Promise<CurrentUser> {
  const user = await getCurrentUser();
  if (!user) {
    redirect(redirectTo);
  }
  return user;
}
