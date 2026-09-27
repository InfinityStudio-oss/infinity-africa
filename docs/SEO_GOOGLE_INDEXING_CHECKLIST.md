# Google Indexing Checklist

Official domain: **https://infinitypay.me**

## The problem this addresses

Searching "InfinityPay" returns several unrelated companies of the same
name — infinitypay.net, infinitypay.app, infinitypay.co.tz and others —
and infinitypay.me was not clearly the official result.

Two separate causes, and only one of them was about wording.

## The actual bug: every page canonicalised to the homepage

`alternates.canonical` was set on the **root layout**. Next merges metadata
down the tree, so every page that did not override it inherited that value.
The shipped HTML for `/solutions`, `/contact` and all 14 developer-docs
pages contained:

```html
<link rel="canonical" href="https://infinitypay.me"/>
```

That tells Google those pages are duplicates of the homepage and should not
be indexed separately. The site was effectively self-deindexing down to a
single URL, leaving nothing to establish topical depth or brand presence —
which is exactly the position a domain needs to be in to outrank unrelated
namesakes.

Fixed by removing the canonical from the root layout and giving every
public page a self-referencing one. `seo-and-security.test.ts` fails if a
root-level canonical is ever reintroduced, and separately if any sitemap
entry stops pointing at itself.

## What is indexable

| Page | Canonical |
|---|---|
| `/` | `https://infinitypay.me/` |
| `/solutions`, `/create-account`, `/contact`, `/report-transaction` | self |
| `/api-docs`, `/privacy`, `/terms` | self |
| `/developers` + 14 docs pages | self |

`/get-started` is **not** in the sitemap: it only redirects to
`/create-account`, and a redirect in a sitemap is reported as an error in
Search Console.

## What is not indexable

Blocked in `robots.ts` **and** carrying `robots: { index: false }` on the
route group's own layout, so a crawler that ignores one still hits the
other:

`/dashboard`, `/merchant` (old paths still resolve via redirects),
`/portal`, `/super-admin`, `/admin`, `/admin-login`, `/admin-mfa`, `/auth`,
`/login`, `/onboarding`, `/pay`, `/payment-links`, `/invoices`, `/api`,
`/v1`.

That covers merchant dashboards, Super Admin, checkout sessions, receipts
with customer details, API-key pages, webhook settings, wallet/ledger and
withdrawals.

## Titles and positioning

The root layout sets `template: "%s | InfinityPay Tanzania"`. The country
is in the suffix deliberately — the bare brand name is contested, so every
indexed page carries the thing that distinguishes this one.

Homepage title:
`InfinityPay Tanzania | Payment Gateway for Merchants, Apps & WiFi Billing`

Pages that already ended in `| InfinityPay` had that suffix removed, or
they would now read `Solutions | InfinityPay | InfinityPay Tanzania`.

## Structured data

`src/components/marketing/structured-data.tsx` renders a JSON-LD `@graph`
on the homepage with `FinancialService` and `WebSite` nodes: the official
URL, `alternateName` of "InfinityPay Tanzania" and "InfinityPay.me",
`areaServed` Tanzania, a Dar es Salaam address, and the real sales and
support contacts already published on the contact page.

Two deliberate omissions:

- **No `sameAs`.** This codebase has no record of official social
  profiles, and a wrong or dead profile link is worse for an entity claim
  than no link.
- **No `SearchAction`.** There is no site search, and declaring an endpoint
  that 404s is worse than declaring none.

## Social preview

`og/infinitypay-og-v2.png`, 1200×630, absolute URL,
`og:site_name = InfinityPay`, `twitter:card = summary_large_image`.

The **v2 filename matters**: the v1 file was edited in place when the logo
changed from the infinity glyph to the hexagon mark, and WhatsApp, Discord
and X cache link previews **by URL**. Reusing the filename would have kept
serving the old glyph indefinitely. Even with the new name, existing shared
links may show the old preview until those caches expire.

## Google Search Console — manual steps after deploy

1. Open https://infinitypay.me/robots.txt — confirm it loads and lists the
   sitemap.
2. Open https://infinitypay.me/sitemap.xml — confirm it lists the public
   pages and nothing private.
3. Add the property in Search Console. **Prefer Domain property** over URL
   prefix: it covers http/https and www/non-www in one, which matters here
   because canonical is non-www.
4. Verify. If using the HTML-tag method, put the token in Vercel as
   `NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION` (Project → Settings → Environment
   Variables → Production) and redeploy. With no value the meta tag is
   omitted entirely. DNS verification needs no code change and is the
   better option for a Domain property.
5. Submit `https://infinitypay.me/sitemap.xml`.
6. URL Inspection on `https://infinitypay.me` → **Request indexing**.
7. Repeat step 6 for `/solutions` and `/developers` — those were previously
   canonicalised away and need to be rediscovered as pages in their own
   right.

## What to expect

Days to weeks, not hours. Two things worth knowing:

- Searching the **exact domain** (`infinitypay.me`) will surface the site
  well before searching the brand name does.
- **"InfinityPay" alone will stay competitive.** Other companies hold that
  name and some have far older domains. The realistic goal is to own
  "InfinityPay Tanzania" and "InfinityPay.me", and to be the top result for
  intent searches like "payment gateway Tanzania" or "WiFi billing payment
  Tanzania". Use "InfinityPay Tanzania" rather than bare "InfinityPay" in
  social posts, directory listings and partner pages — each of those is an
  entity signal.

## Redirects still to configure (outside the codebase)

These are DNS/host settings, not code:

- http → https
- www.infinitypay.me → infinitypay.me (canonical is non-www)
- If infinityafrica.net is still live, 301 it to infinitypay.me. **Check
  payment and callback routes before doing so** — a blanket redirect can
  break provider callbacks pointed at the old host.
- Vercel preview domains must never be canonical. They are not, because
  `metadataBase` is hardcoded rather than read from the deployment URL.
