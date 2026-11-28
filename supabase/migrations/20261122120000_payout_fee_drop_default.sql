-- New merchants were being priced at zero instead of at the tariff.
--
-- 20261121110000 made merchant_payout_settings.fee_flat_tzs and
-- fee_percentage nullable so NULL could mean "no negotiated rate, charge
-- the platform tariff" and 0 could mean "priced at zero, on purpose".
-- It dropped NOT NULL and forgot to drop the DEFAULT 0 that came with
-- the original columns.
--
-- So every row inserted without naming those columns still got 0 - and
-- the row that matters is the one the new access-request flow creates.
-- The first real merchant to use it, SAVANNA TECH (27000008), asked for
-- payout access on 2026-11-22 and landed on fee 0.0% / flat 0.00. The
-- Super Admin screen correctly reported that as a deliberate zero
-- rather than "Standard (tariff)", because that is exactly what the
-- data said. Every merchant requesting access from here would have had
-- free payouts, and nothing would have looked wrong.
--
-- The distinction only works if absent really means absent.

begin;

alter table public.merchant_payout_settings
  alter column fee_flat_tzs drop default,
  alter column fee_percentage drop default;

-- Repair the rows the default created. Narrowed hard: only rows that
-- arrived through a request and that no administrator has ever edited.
-- updated_by is stamped by every admin write, so a zero somebody
-- actually chose is left alone - the same guard the first backfill used,
-- and for the same reason.
update public.merchant_payout_settings
   set fee_flat_tzs = null,
       fee_percentage = null
 where updated_by is null
   and access_requested_at is not null
   and coalesce(fee_flat_tzs, 0) = 0
   and coalesce(fee_percentage, 0) = 0;

commit;
