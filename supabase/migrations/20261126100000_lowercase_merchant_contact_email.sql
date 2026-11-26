-- merchants.contact_email is stored however it was typed. The login
-- address is not: Supabase Auth lowercases that one. So the same person
-- can be written two ways, and the difference is invisible.
--
-- A business record holding "Ixample@gmail.com" whose owner signs in as
-- "ixample@gmail.com" reads identically on screen, because in the
-- portal's font a capital I and a lowercase l are the same glyph.
-- Whoever reads the contact address aloud to help cannot tell which
-- letter it starts with; the address they read back does not exist, and
-- the login answers "Incorrect email or password" - true, and useless.
-- That is a real support call, not a hypothetical.
--
-- Five merchant rows are stored mixed-case today and every one of them
-- contains an I or an l, so every one is ambiguous. (Deliberately not
-- listed here: this repository is public and those are real customer
-- addresses. The verification query at the bottom names them to whoever
-- runs it.)
--
-- Lowercasing is safe. The local part of an address is case-sensitive
-- by RFC and case-insensitive at every provider anyone here uses, and
-- Supabase has already made exactly this decision for the address that
-- actually controls access.
--
-- --- Why a trigger and not a CHECK constraint
--
-- A CHECK would make the invariant real by REJECTING a mixed-case
-- write. On a live payments platform that turns a future code path
-- which forgets to normalise into a failed signup - a hard error on a
-- revenue path, to enforce what is otherwise a cosmetic rule. A BEFORE
-- trigger cannot fail that way: it normalises, and the write succeeds.
--
-- The application normalises too (the business_email validator in
-- app/schemas/onboarding.py, and the Super Admin correction service).
-- This is the belt to those braces, and the part that still holds when
-- a path nobody thought of writes the column.

-- No explicit begin/commit: the Supabase SQL editor already wraps
-- what you paste in a transaction, and a second one only produces a
-- confusing "there is already a transaction in progress" warning.
-- Without a wrapper the order still holds - the backfill runs before
-- the trigger exists, which is harmless, and the trigger then keeps
-- every later write in line.

-- 1. The rows that already exist.
update public.merchants
   set contact_email = lower(contact_email)
 where contact_email is not null
   and contact_email <> lower(contact_email);

-- 2. Nothing can reintroduce it.
create or replace function public.lowercase_merchant_contact_email()
returns trigger
language plpgsql
-- Pinned, like every other function in this schema. An unpinned
-- search_path lets whoever can set it decide which `lower` this
-- resolves to. The platform's own daily security check asserts that
-- every function pins it, and it caught this one missing.
set search_path = pg_catalog, public, pg_temp
as $$
begin
  if new.contact_email is not null then
    new.contact_email := lower(new.contact_email);
  end if;
  return new;
end;
$$;

comment on function public.lowercase_merchant_contact_email() is
  'Keeps merchants.contact_email comparable with the Supabase Auth login '
  'address, which is always lowercase. A capital I and a lowercase l are '
  'the same glyph in most fonts, so a mixed-case address cannot be read '
  'aloud or retyped reliably.';

drop trigger if exists merchants_lowercase_contact_email on public.merchants;

create trigger merchants_lowercase_contact_email
  before insert or update of contact_email on public.merchants
  for each row
  execute function public.lowercase_merchant_contact_email();


-- Verification. Expect ZERO rows: no merchant left whose contact_email
-- differs from its own lowercase form.
select id, business_name, contact_email
  from public.merchants
 where contact_email is not null
   and contact_email <> lower(contact_email);

-- And the trigger is attached. Expect one row, tgenabled = 'O'.
select tgname, tgenabled
  from pg_trigger
 where tgname = 'merchants_lowercase_contact_email'
   and not tgisinternal;
