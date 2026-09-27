/**
 * schema.org JSON-LD for the public homepage.
 *
 * The reason this exists is disambiguation. Searching "InfinityPay"
 * returns several unrelated companies using the same name — infinitypay.net,
 * infinitypay.app, infinitypay.co.tz and others — and nothing in the markup
 * previously told Google which entity this site belongs to. Structured data
 * states it explicitly: the country, the industry, the contact details, and
 * the canonical URL.
 *
 * Every value here is real and already published elsewhere on the site
 * (the contact page carries the same phone and addresses). Nothing is
 * invented to fill a field: `sameAs` is omitted entirely rather than
 * pointing at social profiles this codebase has no record of, because a
 * wrong or dead profile link is worse for an entity claim than no link.
 */

const ORGANIZATION = {
  "@type": "FinancialService",
  "@id": "https://infinitypay.me/#organization",
  name: "InfinityPay",
  alternateName: ["InfinityPay Tanzania", "InfinityPay.me"],
  url: "https://infinitypay.me",
  logo: {
    "@type": "ImageObject",
    url: "https://infinitypay.me/brand/infinity-mark.png",
  },
  image: "https://infinitypay.me/og/infinitypay-og-v2.png",
  description:
    "Tanzanian payment gateway platform for merchants, ecommerce websites, apps, and WiFi/ISP billing systems.",
  areaServed: {
    "@type": "Country",
    name: "Tanzania",
  },
  address: {
    "@type": "PostalAddress",
    addressLocality: "Dar es Salaam",
    addressCountry: "TZ",
  },
  contactPoint: [
    {
      "@type": "ContactPoint",
      contactType: "sales",
      email: "info@infinitypay.me",
      telephone: "+255747730270",
      areaServed: "TZ",
      availableLanguage: ["en", "sw"],
    },
    {
      "@type": "ContactPoint",
      contactType: "customer support",
      email: "support@infinitypay.me",
      areaServed: "TZ",
      availableLanguage: ["en", "sw"],
    },
  ],
};

const WEBSITE = {
  "@type": "WebSite",
  "@id": "https://infinitypay.me/#website",
  name: "InfinityPay",
  alternateName: "InfinityPay Tanzania",
  url: "https://infinitypay.me",
  inLanguage: "en",
  publisher: { "@id": "https://infinitypay.me/#organization" },
  // No `potentialAction`/SearchAction: the site has no search endpoint, and
  // declaring one that 404s is worse than declaring none.
};

const GRAPH = {
  "@context": "https://schema.org",
  "@graph": [ORGANIZATION, WEBSITE],
};

export function StructuredData() {
  return (
    <script
      type="application/ld+json"
      // JSON.stringify output, not author-controlled markup — but the "</"
      // sequence would still close the script tag early if it ever appeared
      // in a value, so it is escaped.
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(GRAPH).replace(/</g, "\\u003c"),
      }}
    />
  );
}
