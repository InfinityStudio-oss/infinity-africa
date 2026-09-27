-- Normalized failure reasons on collections.
--
-- `failure_reason` has always been free text, and several paths wrote the
-- provider's own `message` into it. That value reaches the merchant
-- ledger, the public payment page and the outbound webhook, which makes it
-- two problems at once: a partner cannot branch on prose that changes
-- whenever the provider rewords it, and provider text is not ours to
-- forward verbatim.
--
-- These columns add a stable code a partner can switch on, and a sentence
-- written for a merchant to read. See app/services/failure_reasons.py for
-- the vocabulary and for which mappings are evidenced rather than assumed.
--
-- Purely additive. `failure_reason` is left exactly as it is, including on
-- every historical row: nothing is rewritten or backfilled, so no existing
-- reader changes behaviour and no past transaction is reinterpreted.

alter table public.collections
  add column if not exists failure_reason_code text,
  add column if not exists failure_reason_message text,
  add column if not exists provider_status_code text,
  add column if not exists failed_at timestamptz,
  add column if not exists cancelled_at timestamptz;

comment on column public.collections.failure_reason_code is
  'Stable, machine-readable failure reason from app/services/failure_reasons.py (insufficient_balance, wrong_pin, user_cancelled, timeout, provider_unavailable, provider_declined, expired, reversed, unknown_provider_error). Safe to switch on; published in the API docs. Null while the collection has not failed.';
comment on column public.collections.failure_reason_message is
  'Merchant-facing sentence for failure_reason_code. Never the provider''s own message text.';
comment on column public.collections.provider_status_code is
  'The provider''s raw resultcode, kept for support and reconciliation. Internal: never returned by the public API and never shown to a merchant.';
comment on column public.collections.failed_at is
  'When the collection reached a terminal failed state.';
comment on column public.collections.cancelled_at is
  'When the customer cancelled, for the cancellation subset of failures.';

-- Partial: failed collections are the small minority, and this index only
-- exists to support "why did these fail" reporting.
create index if not exists collections_failure_reason_code_idx
  on public.collections (merchant_id, failure_reason_code)
  where failure_reason_code is not null;
