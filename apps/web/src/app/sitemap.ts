import type { MetadataRoute } from "next";

const BASE_URL = "https://infinitypay.me";

// Public marketing/developer-docs pages only — deliberately excludes every
// private, authenticated, or transaction-specific route (merchant portal,
// super admin, onboarding, auth pages, individual payment-link/invoice/pay
// pages) per robots.ts's disallow list and each of those route groups' own
// `robots: { index: false }` metadata. Static list, not derived from the
// filesystem: a new private route added under app/ should never end up
// here just because someone forgot to also touch this file.
const PUBLIC_PATHS = [
  "/",
  "/solutions",
  "/get-started",
  "/create-account",
  "/contact",
  "/report-transaction",
  "/api-docs",
  "/privacy",
  "/terms",
  "/developers",
  "/developers/authentication",
  "/developers/collections",
  "/developers/curl-examples",
  "/developers/disbursements",
  "/developers/dynamic-qr",
  "/developers/errors",
  "/developers/go-live-checklist",
  "/developers/invoices",
  "/developers/javascript-example",
  "/developers/onboarding-requirements",
  "/developers/payment-links",
  "/developers/python-example",
  "/developers/sandbox",
  "/developers/transaction-status",
  "/developers/webhooks",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return PUBLIC_PATHS.map((path) => ({
    url: `${BASE_URL}${path}`,
    lastModified,
    changeFrequency: path === "/" ? "weekly" : "monthly",
    priority: path === "/" ? 1 : 0.6,
  }));
}
