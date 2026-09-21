import type { MetadataRoute } from "next";

// Belt-and-suspenders alongside the per-route-group `robots: { index: false }`
// metadata (merchant/, portal/, admin/, super-admin/, onboarding/, pay/,
// payment-links/, invoices/, login/, admin-login/ layouts) — a crawler that
// ignores meta robots tags (or reads this file first) still never gets
// pointed at any private/auth/transaction-specific path in the first place.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/merchant",
        "/merchant/",
        "/portal",
        "/portal/",
        "/super-admin",
        "/super-admin/",
        "/admin",
        "/admin/",
        "/admin-login",
        "/login",
        "/onboarding",
        "/pay",
        "/pay/",
        "/payment-links",
        "/payment-links/",
        "/invoices",
        "/invoices/",
        "/api",
        "/v1",
      ],
    },
    sitemap: "https://infinitypay.me/sitemap.xml",
    host: "https://infinitypay.me",
  };
}
