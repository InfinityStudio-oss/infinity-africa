-- Public half of the API key pair.
--
-- Until now a key was a single secret string (`inf_{env}_...`), of which
-- only the SHA-256 hash was stored. Partners integrating InfinityPay into
-- their own platform need a non-secret identifier they can keep in config,
-- show in a dashboard, or quote in support — hence the pk/sk pair, matching
-- the convention those integrators already expect from other gateways.
--
-- public_key is stored in PLAINTEXT on purpose: it is not a credential.
-- It identifies a key/merchant/environment and must never authenticate a
-- request on its own — app/auth/dependencies.py only ever matches against
-- hashed_key, and rejects a `pk_` outright with a distinct error.
--
-- Nullable, deliberately. Keys issued before this migration have no public
-- half and must keep working exactly as they do now: authentication matches
-- hashed_key, which is unchanged, so every existing `inf_...` key is
-- unaffected. Backfilling one would invent an identifier the merchant has
-- never seen, so those rows simply show no public key until rotated.
--
-- This does NOT touch merchants.merchant_code — the permanent 27-series
-- Merchant ID is the account identity and is not a credential. An API key
-- is per-integration and revocable; the Merchant ID is neither.

alter table public.api_keys
  add column if not exists public_key text;

comment on column public.api_keys.public_key is
  'Plaintext public half of the key pair (pk_test_/pk_live_). Safe to display: identifies the key and its environment, never authorizes a request. Null for keys issued before the pair existed.';

-- Unique where present, so a public key always names exactly one row when
-- it is used as a lookup for display or support. Partial, because the
-- pre-existing keys legitimately share a null.
create unique index if not exists api_keys_public_key_key
  on public.api_keys (public_key)
  where public_key is not null;
