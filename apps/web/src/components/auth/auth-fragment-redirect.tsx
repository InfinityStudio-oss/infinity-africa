"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Supabase's admin-generated recovery/invite links carry a `redirect_to`
 * pointing at the real destination (e.g. /dashboard/reset-password), but
 * Supabase silently falls back to the bare Site URL (this homepage)
 * whenever it decides that redirect_to isn't valid — a long-standing,
 * documented Supabase quirk (supabase/auth#1738 and others), not
 * something a Redirect URLs allow-list entry alone reliably fixes. The
 * auth tokens still arrive even on the fallback, as a query string or
 * hash fragment — they're just on the wrong page. This catches that
 * fragment here and forwards it to wherever it actually belongs, so the
 * flow completes instead of silently dead-ending on the marketing
 * homepage. Mounted only on the root "/" page, since that's the one
 * Supabase's fallback ever targets.
 */
const TYPE_TO_PATH: Record<string, string> = {
  recovery: "/dashboard/reset-password",
  invite: "/dashboard/invite/accept",
};

export function AuthFragmentRedirect() {
  const router = useRouter();

  useEffect(() => {
    const url = new URL(window.location.href);
    const hash = new URLSearchParams(url.hash.startsWith("#") ? url.hash.slice(1) : url.hash);

    const type = url.searchParams.get("type") ?? hash.get("type");
    const hasToken =
      url.searchParams.has("code") ||
      url.searchParams.has("token_hash") ||
      hash.has("access_token") ||
      hash.has("token_hash");

    if (!hasToken || !type) return;
    const target = TYPE_TO_PATH[type];
    if (!target) return;

    router.replace(`${target}${url.search}${url.hash}`);
  }, [router]);

  return null;
}
