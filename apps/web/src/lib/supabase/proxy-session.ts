import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { isSupabaseConfigured } from "@/lib/auth/supabase-status";

/**
 * Refreshes the Supabase session cookie on every request, per the
 * @supabase/ssr Next.js pattern — this used to live in middleware.ts; Next
 * 16 renamed that file to proxy.ts (see apps/web/src/proxy.ts).
 *
 * Must fail open: this repo's .env.local currently points at an unreachable
 * local Supabase instance (http://localhost:54321, nothing listening), so
 * an unguarded call here would hang/error on every single page load.
 */
export async function updateSession(request: NextRequest): Promise<NextResponse> {
  let response = NextResponse.next({ request });

  if (!isSupabaseConfigured()) {
    return response;
  }

  try {
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll() {
            return request.cookies.getAll();
          },
          setAll(cookiesToSet) {
            cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
            response = NextResponse.next({ request });
            cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
          },
        },
      },
    );

    // getSession(), NOT getUser(), and the difference is a network round
    // trip on every single request this proxy matches.
    //
    // getUser() always calls Supabase Auth over the network to revalidate
    // the JWT. getSession() reads the cookie and only goes to the network
    // when the access token is within EXPIRY_MARGIN_MS (90s) of expiring,
    // which is when it refreshes and writes the new cookie through setAll
    // above. Refreshing that cookie is the ONLY reason this function
    // exists - a Server Component cannot set cookies, so the refresh has
    // to happen here.
    //
    // Nothing is weakened by the swap, because the result was always
    // thrown away. This made no authorization decision before and makes
    // none now; every page still proves who the caller is with its own
    // getUser() (lib/supabase/session.ts), which is the call that must
    // stay a revalidating one. What was removed is the SECOND, duplicate
    // revalidation of the same token in the same request.
    //
    // Measured from Dar es Salaam, 2026-11-28: the portal renders in
    // Frankfurt (x-vercel-id cpt1::fra1) and this was one of three serial
    // hops before a page could paint.
    await supabase.auth.getSession();
  } catch {
    // Connectivity failure (or any other Supabase error) — fail open and
    // let the request through unmodified.
  }

  return response;
}
