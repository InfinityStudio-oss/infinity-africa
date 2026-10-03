import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

import { AnalyticsProvider } from "@/components/providers/analytics-provider";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

// "Tanzanian" leads both of these. Searching "InfinityPay" returns several
// unrelated companies of the same name, so the country is the thing that
// tells a reader — and a ranking algorithm — which one this is.
const SITE_DESCRIPTION =
  "InfinityPay is a Tanzanian payment gateway for merchants, ecommerce websites, apps, and WiFi/ISP billing systems. Accept mobile money payments, create payment links, issue invoices, track your wallet ledger, and integrate with our APIs.";
const OG_DESCRIPTION =
  "Tanzanian payment gateway for merchants, ecommerce, apps and WiFi/ISP billing. Mobile money collections, payment links, invoices, wallet ledger and developer APIs.";

// Versioned filename (v2 — the v1 image was edited in place when the logo
// changed from the infinity glyph to the hexagon mark, and link-preview
// caches are keyed by URL, so reusing the name would have kept serving the
// old glyph. v1 under the InfinityPay brand superseded the old
// infinity-africa-og-v2.png, itself the successor to the original
// infinity-logo-v2.png glossy stock-art mark, never actually used anywhere
// in the live app; see apps/web/scripts/generate-og-image.mjs) so
// Discord/WhatsApp/X's own link-preview caches, keyed by URL, pick up the
// new image on next crawl rather than continuing to serve an old cached
// copy of the same filename indefinitely.
const OG_IMAGE_URL = "https://infinitypay.me/og/infinitypay-og-v2.png";

export const metadata: Metadata = {
  title: {
    // Child pages supply their own title and get the brand suffix for
    // free. "Tanzania" is in the suffix deliberately: the bare name
    // "InfinityPay" is used by several unrelated companies, so every
    // indexed page carries the country that distinguishes this one.
    template: "%s | InfinityPay Tanzania",
    default: "InfinityPay Tanzania | Payment Gateway for Merchants, Apps & WiFi Billing",
  },
  description: SITE_DESCRIPTION,
  metadataBase: new URL("https://infinitypay.me"),
  // NO canonical here on purpose. Next merges metadata down the tree, so a
  // canonical set on the root layout is inherited by every page that does
  // not override it — which shipped `<link rel="canonical"
  // href="https://infinitypay.me">` on /solutions, /contact and all 14
  // developer docs pages, telling Google they were duplicates of the
  // homepage and should not be indexed separately. Each public page now
  // declares its own; the homepage's lives in app/page.tsx.
  openGraph: {
    title: "InfinityPay Tanzania",
    description: OG_DESCRIPTION,
    url: "https://infinitypay.me/",
    siteName: "InfinityPay",
    images: [{ url: OG_IMAGE_URL, width: 1200, height: 630, alt: "InfinityPay Tanzania" }],
    locale: "en_US",
    type: "website",
  },
  // Google Search Console verification. Read from the environment so the
  // token is set per deployment rather than committed — it is a public
  // value (it ships in the HTML), but it identifies an account, so it does
  // not belong in the repo. Omitted entirely when unset, which is what
  // Next does with an undefined verification block.
  verification: process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION
    ? { google: process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION }
    : undefined,
  twitter: {
    card: "summary_large_image",
    title: "InfinityPay Tanzania",
    description: "Tanzanian payment gateway for merchants, ecommerce, apps and WiFi/ISP billing.",
    images: [OG_IMAGE_URL],
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <head>
        {/* Sets .icons-pending before the body paints, so a Material Symbols
            ligature is never shown as its own name ("smartphone",
            "qr_code_scanner") while the icon font is still loading. Inline
            and synchronous on purpose: anything deferred runs after first
            paint, which is exactly the frame we need to cover.

            This POLLS document.fonts.check rather than awaiting
            document.fonts.load. load() resolves with the faces that
            matched — and this script runs before the stylesheet below has
            been fetched and parsed, so at that moment NO face is declared
            for the family, nothing matches, and the promise resolves
            immediately. The guard was being removed within a frame or two
            of being set, which is why the names still flashed on a cold
            load. check() instead returns false until the font is really
            usable.

            Still shows on a timeout: a font that never arrives must not
            leave the UI permanently iconless. Five seconds rather than
            three, since the losing case here is a slow mobile connection,
            which is the normal case for this platform's users. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){var d=document.documentElement,F='24px "Material Symbols Outlined"',t0=Date.now(),done=false;d.classList.add('icons-pending');function show(){if(done)return;done=true;d.classList.remove('icons-pending')}if(!document.fonts||!document.fonts.check){show();return}try{document.fonts.load(F)}catch(e){}(function poll(){if(done)return;if(document.fonts.check(F))return show();if(Date.now()-t0>5000)return show();setTimeout(poll,100)})()})();`,
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
      <body className="min-h-full flex flex-col">
        {children}
        {/* Renders nothing. Mounted here so a pageview is recorded on
            every route, and no-ops entirely when NEXT_PUBLIC_POSTHOG_KEY
            is unset. */}
        <AnalyticsProvider />
      </body>
    </html>
  );
}
