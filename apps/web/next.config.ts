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
  `connect-src 'self' https://*.supabase.co wss://*.supabase.co${apiUrl ? ` ${apiUrl}` : ""}`,
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
};

export default nextConfig;
