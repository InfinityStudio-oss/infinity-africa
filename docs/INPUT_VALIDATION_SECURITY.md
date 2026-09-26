# Input validation

Reviewed 2026-09-26. **One real vulnerability found and fixed** (SSRF via
the merchant webhook URL). Everything else was already validated.

## Where validation lives

Pydantic schemas on the backend are the authority. Every request body is a
typed model, so a field that is a `Literal`, a `UUID`, a `Decimal` or a
constrained `str` is rejected at the boundary before a handler sees it —
there is no "validate then use" step to forget.

Frontend validation exists for UX only. It tells someone their phone number
is wrong before a round trip; it is never what keeps bad data out.

## The vulnerability that was here

`webhook_url` was typed `HttpUrl`, which validates that a string *looks
like* a URL. It does not say anything about where that URL points — and the
backend fetches it, on test deliveries and on every real event.

So a merchant could set `http://169.254.169.254/latest/meta-data/` and have
our infrastructure fetch cloud metadata on their behalf, or sweep internal
addresses and infer what exists from the response timing. That is
server-side request forgery, and the merchant did not need to be
sophisticated to try it.

`app/core/url_safety.py` now refuses, in production:

- anything not `https://` — a webhook carries payment events and a
  signature, both readable and alterable over plain http
- loopback, private, link-local, reserved, multicast and unspecified
  addresses
- the cloud metadata hosts by name

It **resolves the hostname** before deciding, because a name is not a
promise: `evil.test` can have an A record pointing at `127.0.0.1`. Every
resolved address must be public, not just the first.

⚠️ **This is a check at save time, not at send time.** DNS can change
afterwards — a rebinding attack defeats it. It raises the cost of an
attempt rather than making one impossible. Closing that properly means
re-resolving and pinning the address at delivery time, which is worth doing
if webhook volume ever justifies it.

Localhost still works outside production, deliberately, so local
development is not broken.

## Money

Amounts are `Decimal`, never float, so there is no rounding drift. They are
validated positive, bounded by `MIN_WITHDRAWAL_AMOUNT_TZS` /
`MAX_WITHDRAWAL_AMOUNT_TZS`, and checked again against the wallet balance
under a row lock before anything moves. Currency and method are enums, not
free text.

Tested against `-1000`, `0`, `abc`, `1e9999`, `NaN`, `Infinity` and empty —
all refused.

## Query parameters

`page_size` is `Query(20, ge=1, le=100)`, so scraping by asking for a
hundred thousand rows fails at the type boundary rather than in a handler.
Tested at 1000, 100000, -1 and 0.

Path IDs are typed `uuid.UUID`, which is why a SQL payload in a path
segment returns 422 rather than reaching a query.

## SQL and XSS

Every query goes through the Supabase client's builder, which parameterises.
There is no string-concatenated SQL anywhere in `apps/api`, and no
user-controlled table, column or function name.

`dangerouslySetInnerHTML` appears once, in `app/layout.tsx`, and contains a
fixed icon-loading script with no user input. Everything else renders
through React, which escapes by default.

Hostile strings are therefore treated as **data, not rejected**. That is
deliberate: a business genuinely called `O'Brien & Sons` must be able to
sign up. The test asserts such a value comes back byte-identical and that
it changes no query behaviour — not that it is refused.

## Headers

`Authorization` must match a known credential shape; a public key presented
as one is refused with a message naming the mistake.
`X-Forwarded-For` is only ever read through `app/core/request_ip.py`, which
counts in from the right by `TRUSTED_PROXY_HOPS` — reading it directly
anywhere else would reintroduce a spoofable identity.

## File uploads

One endpoint: `POST /v1/onboarding/documents`, guarded by
`get_own_merchant`. Onboarding no longer asks for documents up front —
compliance requests them during review — so it is a low-traffic path.

Three things were weak and are now fixed:

**The declared type was trusted.** `content_type` is a header the uploader
sets, so an executable claiming `image/png` passed the allowlist. The file's
own leading bytes are now checked against the declared type, and those the
uploader does not get to choose.

**There was no size ceiling.** The handler reads the whole file into
memory, so one large upload could exhaust the container for every merchant.
Capped at 10 MB, with a bounded read of one byte past the limit so an
oversized file is rejected without being loaded first.

**The stored extension came from the filename.** `id.pdf.exe` would have
been stored as `.exe`. The extension is now derived from the verified type.
The storage path was already server-generated
(`{merchant_id}/{document_type}{ext}`), so traversal was never possible —
tested with `../../etc/passwd` and friends, which land in the same safe
path as any other name. The original filename is still recorded as data for
whoever reviews the document; it simply has no say in where the file goes.

**Still not implemented: malware scanning.** A valid PDF can carry a
malicious payload, and nothing here would notice. The mitigations that
exist are that the bucket is private and served only through short-lived
signed URLs, and that only approved-merchant staff can upload. Adding
scanning means a third-party service (ClamAV in a sidecar, or a hosted
API), which is a cost and operations decision rather than a code change —
worth taking when document volume grows.

## Adding a new endpoint

1. Give the body a Pydantic model. Use `Literal` for closed sets, `UUID`
   for ids, `Decimal` for money, and constrain string lengths.
2. If the value is a URL **this server will fetch**, pass it through
   `validate_outbound_url`.
3. If it is a list endpoint, use the shared `pagination_params`.
4. Never build a query string from user input.
5. Return a message a user can act on that reveals nothing about the
   internals — no SQL, no provider payloads, no stack traces.
