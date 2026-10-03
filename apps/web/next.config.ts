import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// NEXT_PUBLIC_* vars are baked into the client bundle at build time in
// Next.js — reading it here (also at build time, inside next.config.ts)
// puts exactly the same already-public value into the CSP header for this
// build, nothing extra exposed. Supabase Auth is called directly from the
// browser (apps/web/src/lib/supabase/client.ts) for login/signup/reset —
// the wildcard covers whichever project this deployment points at without
// needing the literal URL hardcoded here.
const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";

// Monitoring endpoints, added to connect-src ONLY when the matching key
// is configured for this build. Both Sentry and PostHog report by POSTing
// to their own host, which `connect-src 'self'` forbids — so without
// these entries the SDKs would initialise, appear healthy, and have every
// single event blocked by the browser. Found before shipping rather than
// after a week of an empty dashboard.
//
// Gated on the env vars so a deploy with monitoring off keeps the
// narrower policy, rather than permanently allowing two extra origins.
const monitoringOrigins = [
  // Sentry's ingest host is per-project and lives inside the DSN:
  // https://<key>@<org>.ingest.<region>.sentry.io/<project>. Only the
  // origin is taken, never the key.
  process.env.NEXT_PUBLIC_SENTRY_DSN ? safeOrigin(process.env.NEXT_PUBLIC_SENTRY_DSN) : "",
  process.env.NEXT_PUBLIC_POSTHOG_KEY
    ? safeOrigin(process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://eu.i.posthog.com")
    : "",
].filter(Boolean);

/** Origin of a URL, or "" if it is unparseable — a malformed DSN must
 * fail by leaving the CSP alone, never by breaking the build. */
function safeOrigin(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return "";
  }
}

// Without-nonce CSP, per node_modules/next/dist/docs/.../content-security-policy.md's
// own "Without Nonces" example — the nonce-based approach forces every page
// to dynamic rendering (no static optimization/ISR), which would undo Part 9's
// performance goals across this app's mostly-static marketing pages for a
// framework that has no analytics/inline third-party scripts to protect
// against in the first place. 'unsafe-inline' on script-src is the one
// deviation from a maximally strict policy — Next's own non-nonce example
// keeps it too, for its own inline bootstrap/hydration scripts; documented
// here rather than silently present. style-src keeps 'unsafe-inline' for
// the same reason (dynamic inline `style={{...}}` usage throughout the
// React tree) plus Google Fonts' own stylesheet.
const cspDirectives = [
  `default-src 'self'`,
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com`,
  `img-src 'self' data: blob:`,
  `font-src 'self' https://fonts.gstatic.com`,
  `connect-src 'self' https://*.supabase.co wss://*.supabase.co${apiUrl ? ` ${apiUrl}` : ""}${
    monitoringOrigins.length ? ` ${monitoringOrigins.join(" ")}` : ""
  }`,
  `object-src 'none'`,
  `base-uri 'self'`,
  `form-action 'self'`,
  `frame-ancestors 'none'`,
  ...(isDev ? [] : ["upgrade-insecure-requests"]),
];

const securityHeaders = [
  // Ignored by browsers over plain http (dev), enforced over https (prod) —
  // per spec, safe to always send.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Belt-and-suspenders with frame-ancestors above for browsers that predate CSP.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
  },
  { key: "Content-Security-Policy", value: cspDirectives.join("; ") },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  // Safe here (unlike on the API): nothing else embeds this frontend's own
  // JS/CSS/images as a cross-origin subresource.
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  transpilePackages: ["@infinity/shared"],
  experimental: {
    serverActions: {
      // Onboarding submission (app/onboarding/page.tsx ->
      // submitOnboardingAction) uploads three real compliance documents
      // (NIDA, TIN certificate, business licence) as a single Server
      // Action request — Next.js's 1MB default body cap rejected a real
      // merchant's submission with a bare "This page couldn't load"
      // (confirmed via Vercel runtime error: "Body exceeded 1 MB limit.",
      // digest 3780544422@E394, 2026-08-29). 15mb comfortably covers
      // three phone-camera photos/scans without opening this up to
      // arbitrary large uploads.
      bodySizeLimit: "15mb",
    },
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
  // The merchant dashboard moved from /merchant/* to /dashboard/*. These
  // permanent redirects keep every old URL working: bookmarks, links in
  // password-reset and staff-invite emails already delivered, and any
  // /merchant/... path a merchant has saved. Without them those all 404.
  //
  // 308 (permanent, method-preserving) rather than 301/302 so a POST to an
  // old URL isn't silently downgraded to GET.
  //
  // Deliberately NOT a catch-all rewrite: the five removed features
  // (payment-links, risk-monitoring, disputes, and the portal's customers
  // and pricing pages) have no destination any more, so /merchant/disputes
  // correctly 404s rather than redirecting somewhere misleading.
  async redirects() {
    return [
      {
        source: "/merchant",
        destination: "/dashboard/overview",
        permanent: true,
      },
      {
        source: "/merchant/:path*",
        destination: "/dashboard/:path*",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
