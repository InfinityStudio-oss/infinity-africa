import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const SITE_DESCRIPTION =
  "Secure payment infrastructure for African merchants. Create payment links, request collections, send invoices, manage wallet ledger, withdrawals, and developer APIs from one platform.";
const OG_DESCRIPTION =
  "Payment infrastructure for African merchants, payment links, invoices, collections, wallet ledger, and merchant tools.";

// Versioned filename (v1 under the InfinityPay brand — supersedes the old
// infinity-africa-og-v2.png, itself the successor to the original
// infinity-logo-v2.png glossy stock-art mark, never actually used anywhere
// in the live app; see apps/web/scripts/generate-og-image.mjs) so
// Discord/WhatsApp/X's own link-preview caches, keyed by URL, pick up the
// new image on next crawl rather than continuing to serve an old cached
// copy of the same filename indefinitely.
const OG_IMAGE_URL = "https://infinitypay.me/og/infinitypay-og-v1.png";

export const metadata: Metadata = {
  title: "InfinityPay | Payment Infrastructure for African Merchants",
  description: SITE_DESCRIPTION,
  metadataBase: new URL("https://infinitypay.me"),
  alternates: {
    canonical: "https://infinitypay.me/",
  },
  openGraph: {
    title: "InfinityPay",
    description: OG_DESCRIPTION,
    url: "https://infinitypay.me/",
    siteName: "InfinityPay",
    images: [{ url: OG_IMAGE_URL, width: 1200, height: 630, alt: "InfinityPay" }],
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "InfinityPay",
    description: "Payment infrastructure for African merchants.",
    images: [OG_IMAGE_URL],
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <head>
        {/* eslint-disable-next-line @next/next/no-page-custom-font -- the
            no-page-custom-font rule predates the App Router; app/layout.tsx
            *is* the documented place for a site-wide font link. */}
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
