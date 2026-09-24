-- Email OTP verification for merchant withdrawals.
--
-- A withdrawal is no longer created when the merchant submits the form.
-- Instead a challenge row is written here, an OTP is emailed to the
-- merchant's own contact address, and only a successful verification
-- creates the disbursement (PENDING_ADMIN_APPROVAL, exactly as before).
--
-- Deliberately a separate table rather than an extra disbursements status:
-- an unverified request must not be visible to, approvable by, or payable
-- from any existing code path. A row here is inert — nothing reads it but
-- the verify endpoint — so a stale or abandoned challenge can never become
-- money movement. It also means no existing query, sweep, reconciliation
-- job or Super Admin view needs to learn a new status to stay correct.
--
-- The OTP itself is never stored. Only a SHA-256 hash is kept, the same
-- one-way treatment API keys get (app/auth/hashing.py).

create table if not exists public.merchant_withdrawal_otp_challenges (
  id uuid primary key default gen_random_uuid(),

  merchant_id uuid not null references public.merchants (id) on delete cascade,
  -- Who asked. A challenge is only ever verifiable by the user who created
  -- it, not merely by anyone holding that merchant's session.
  requested_by uuid not null references auth.users (id) on delete cascade,

  -- The withdrawal exactly as requested, replayed verbatim on verify. The
  -- merchant never re-sends it, so the amount and destination that were
  -- emailed are the ones that get created.
  withdrawal_payload jsonb not null,
  -- SHA-256 over the canonical payload. Binds the OTP to this specific
  -- amount/method/destination: editing any field after the code was sent
  -- produces a different hash and a different challenge, so a code issued
  -- for 1,000 TZS can never approve 1,000,000.
  payload_hash text not null,

  otp_hash text not null,

  expires_at timestamptz not null,
  attempts integer not null default 0,
  max_attempts integer not null default 5,
  -- Set once, on success. A second verify of the same challenge is a no-op
  -- rather than a second withdrawal.
  used_at timestamptz,
  -- Set when attempts are exhausted. Distinct from expiry so the failure
  -- can be told apart in an audit, though both look identical to the caller.
  locked_at timestamptz,

  resend_count integer not null default 0,
  last_sent_at timestamptz not null default now(),

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.merchant_withdrawal_otp_challenges is
  'Pending email-OTP verifications for merchant withdrawal requests. A row here is NOT a withdrawal: nothing is created, reserved, or payable until the OTP is verified, at which point a normal PENDING_ADMIN_APPROVAL disbursement is created. Rows are inert and safe to leave or purge.';
comment on column public.merchant_withdrawal_otp_challenges.otp_hash is
  'SHA-256 of the 6-digit code. The code itself is never stored, logged, or returned by any endpoint.';
comment on column public.merchant_withdrawal_otp_challenges.payload_hash is
  'SHA-256 of the canonical withdrawal payload, binding the code to one specific amount and destination.';

create index if not exists mw_otp_merchant_created_idx
  on public.merchant_withdrawal_otp_challenges (merchant_id, created_at desc);

-- Used by the resend-cooldown and active-challenge lookups, which only ever
-- care about rows that are still live.
create index if not exists mw_otp_active_idx
  on public.merchant_withdrawal_otp_challenges (merchant_id, expires_at)
  where used_at is null and locked_at is null;

-- For purging expired rows.
create index if not exists mw_otp_expires_idx
  on public.merchant_withdrawal_otp_challenges (expires_at);

alter table public.merchant_withdrawal_otp_challenges enable row level security;

-- No policies: this table is reached only by the service role through the
-- backend, never by an authenticated browser session. RLS on with zero
-- policies means anon/authenticated get nothing, which is the intent — the
-- OTP hash must not be readable by the very client being challenged.
