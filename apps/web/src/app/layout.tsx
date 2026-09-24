import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const SITE_DESCRIPTION =
  "Secure payment infrastructure for African businesses and service providers. Create Pay by Links, request collections, send invoices, manage wallet ledger, withdrawals, and developer APIs from one platform.";
const OG_DESCRIPTION =
  "Payment infrastructure for African businesses and service providers, Pay by Links, invoices, collections, wallet ledger, and business tools.";

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
    description: "Payment infrastructure for African businesses and service providers.",
    images: [OG_IMAGE_URL],
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <head>
        {/* Sets .icons-pending before the body paints, so a Material Symbols
            ligature is never shown as its own name ("smartphone",
            "qr_code_scanner") while the icon font is still loading. Removed
            as soon as the font is usable, and on a timeout so icons can
            never stay hidden if the font fails outright. Inline and
            synchronous on purpose: anything deferred runs after first paint,
            which is exactly the frame we need to cover. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){var d=document.documentElement;d.classList.add('icons-pending');function show(){d.classList.remove('icons-pending')}if(document.fonts&&document.fonts.load){document.fonts.load('24px "Material Symbols Outlined"').then(show).catch(show)}else{show()}setTimeout(show,3000)})();`,
          }}
        />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font, @next/next/google-font-display --
            no-page-custom-font predates the App Router; app/layout.tsx *is*
            the documented place for a site-wide font link.
            google-font-display warns against display=block because, for a
            *text* font, it means invisible text while the font loads. This
            is an *icon* font: the fallback does not render a blank, it
            renders the ligature's name as readable words over the UI.
            display=block is what Google's own Material Symbols guidance
            recommends for exactly this reason. */}
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=block"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
