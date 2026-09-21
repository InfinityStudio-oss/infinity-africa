# InfinityPay

Payment infrastructure for merchants — collections, payment links, invoices,
and disbursements.

## Stack

| Layer          | Technology                  | Hosting  |
| -------------- | ---------------------------- | -------- |
| Frontend       | Next.js (App Router), TypeScript, Tailwind CSS | Vercel   |
| Backend        | FastAPI (Python)             | Railway  |
| Database & Auth | Supabase                    | Supabase |

## Monorepo structure

```
infinity/
├── apps/
│   ├── web/        # Next.js frontend — landing page, customer payment
│   │                  page, merchant portal, super admin dashboard
│   └── api/         # FastAPI backend
├── packages/
│   └── shared/       # Shared TypeScript constants & enums
├── supabase/
│   └── migrations/   # SQL schema migrations (Supabase CLI convention)
└── docs/             # API docs & implementation notes
```

## Prerequisites

- Node.js 20+ and npm
- Python 3.12+
- A Supabase project (database + auth)

## Run locally

### 1. Frontend (`apps/web`)

```bash
npm install                 # from the repo root — installs all workspaces
cp apps/web/.env.example apps/web/.env.local
npm run dev:web              # http://localhost:3000
```

### 2. Backend (`apps/api`)

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS/Linux

pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload   # http://localhost:8000
```

Health check: `GET http://localhost:8000/health`

### 3. Database (`supabase/migrations`)

Requires the [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started):

```bash
supabase link --project-ref <your-project-ref>   # link to a Supabase project
supabase db push                                  # apply supabase/migrations/*.sql
```

Or run `supabase start` for a local Postgres instance and `supabase db reset`
to apply migrations against it.

## Status

Project foundation — routing, structure, tooling, and the database schema
are in place. No payment provider integrations or auth wiring yet.

See [`docs/implementation-notes.md`](docs/implementation-notes.md) for
architecture notes.
