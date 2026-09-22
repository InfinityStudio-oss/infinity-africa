"use server";

import { redirect } from "next/navigation";

import { clearMockSession } from "@/lib/auth/mock-session";

import { createClient } from "./server";

async function signOutEverywhere() {
  try {
    const supabase = await createClient();
    await supabase.auth.signOut();
  } catch {
    // Supabase unreachable (mock-auth fallback environment) — the mock
    // session cookie cleared below is the actual source of truth there.
  }
  await clearMockSession();
}

export async function logout() {
  await signOutEverywhere();
  redirect("/login");
}

/** Same sign-out, but back to the Merchant Portal's own login page rather
 * than the generic /login — used by the merchant portal topbar so a
 * signed-out merchant lands somewhere they can sign back in as a merchant. */
export async function merchantLogout() {
  await signOutEverywhere();
  redirect("/dashboard/login");
}

/** Same sign-out, but back to the Super Admin console's own login page
 * (/admin-login) rather than the generic /login. */
export async function adminLogout() {
  await signOutEverywhere();
  redirect("/admin-login");
}
