-- Withdrawal automation (business request: reduce approval delays for
-- low-risk merchants without removing the safety net — see
-- app/services/disbursements.py::_evaluate_auto_withdrawal_eligibility
-- and Settings.auto_withdrawals_enabled). Deliberately does NOT add a new
-- status value (e.g. an "AUTO_PROCESSING" enum member) — every existing
-- status transition, reconciliation sweep, and refresh path keeps working
-- unchanged for an auto-approved disbursement exactly as it does for a
-- manually-approved one; only these two columns distinguish "how did this
-- get approved" from the state machine itself.

alter table public.disbursements
  add column if not exists auto_approved boolean not null default false,
  add column if not exists auto_decision_reason text;

comment on column public.disbursements.auto_approved is
  'True if this withdrawal skipped Super Admin approval via the automated eligibility check (approved_by/approved_at stay null in that case — no human approved it). False (the default) for every manually-approved or still-pending withdrawal.';
comment on column public.disbursements.auto_decision_reason is
  'Why the automated eligibility check did or did not auto-process this withdrawal (e.g. "eligible: within auto-withdrawal limits" or "manual approval required: exceeds per-transaction auto limit"). Null for withdrawals created before this feature, or while AUTO_WITHDRAWALS_ENABLED is off.';

create index if not exists disbursements_auto_approved_idx on public.disbursements (auto_approved) where auto_approved;
