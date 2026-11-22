-- Let the merchant OTP challenge cover payout-wallet funding too.
--
-- Funding the payout wallet demanded assurance_level 'aal2'. No merchant
-- can reach that: MFA enrolment exists only under /admin-mfa, for Super
-- Admins, and the merchant portal has no enrolment and no challenge
-- flow at all. Checked on the pilot account - factors = 0. So the error
-- "Funding the payout wallet requires two-factor authentication.
-- Complete the MFA challenge and try again" was accurate, impossible to
-- act on, and shown to every merchant who tried. Nobody could fund a
-- payout wallet; the pilot's TZS 10,000 only exists because it was
-- written directly.
--
-- Merchants already HAVE a second factor for moving money - the emailed
-- OTP on withdrawals. It is the right one to reuse: they know it, it
-- needs no enrolment, and funding deserves exactly the same treatment as
-- a withdrawal because it is the same kind of act (deciding how much
-- money is exposed).
--
-- So this is one column, not a second OTP system. Same table, same
-- hashing, same expiry, attempt limits, lockout and resend cooldown. A
-- second implementation of a security control is a second one to get
-- wrong.
--
-- Default 'withdrawal' so every existing row keeps its meaning and no
-- in-flight challenge is disturbed.

begin;

alter table public.merchant_withdrawal_otp_challenges
  add column if not exists purpose text not null default 'withdrawal';

alter table public.merchant_withdrawal_otp_challenges
  drop constraint if exists merchant_withdrawal_otp_challenges_purpose_check;

alter table public.merchant_withdrawal_otp_challenges
  add constraint merchant_withdrawal_otp_challenges_purpose_check
  check (purpose in ('withdrawal', 'payout_funding'));

comment on column public.merchant_withdrawal_otp_challenges.purpose is
  'What the code authorises. Challenges are superseded within a purpose only: asking to fund a payout wallet must not silently kill a withdrawal code the merchant is halfway through typing.';

-- The supersede lookup and the "do I have a live challenge" read are
-- both per merchant AND per purpose now, so the index follows.
create index if not exists merchant_withdrawal_otp_challenges_live_idx
  on public.merchant_withdrawal_otp_challenges (merchant_id, purpose, expires_at desc)
  where used_at is null and locked_at is null;

commit;
