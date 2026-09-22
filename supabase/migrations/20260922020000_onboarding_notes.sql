-- Optional free-text "notes / description" field on the Get Started
-- signup form, distinct from the already-required nature_of_business
-- column — this one is genuinely optional and never validated.

alter table public.onboarding_submissions
  add column if not exists notes text;

comment on column public.onboarding_submissions.notes is
  'Optional free-text notes/description provided at signup. Never required, unlike nature_of_business.';
