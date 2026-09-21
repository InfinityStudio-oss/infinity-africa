# apps/api — InfinityPay backend

FastAPI backend, deployed on Railway.

## Structure

```
app/
├── main.py         # FastAPI app instance, CORS, router registration, exception handlers
├── config/         # Settings (env vars)
├── auth/           # JWT verification, role enforcement, API key auth (see docs/api.md)
├── core/           # Error types, pagination, response envelope, reference IDs
├── routers/        # API route handlers — one file per /v1 resource
├── services/        # Business logic: CRUD helpers, idempotency, audit log,
│                      ledger posting, webhook enqueueing, payment providers
├── schemas/        # Pydantic request/response models & shared enums
├── database/       # DB session / Supabase client setup
└── middleware/      # Custom ASGI middleware (none yet)
tests/
├── fakes.py        # In-memory supabase-py stand-in used by conftest.py
├── conftest.py     # fake_client fixture — patches it into every module
│                      that calls get_supabase_admin()
└── factories.py    # Shared seed helpers (create_merchant, auth_headers, ...)
```

See [`docs/api.md`](../../docs/api.md) for the endpoint list, auth, and
idempotency rules.

## Environment variables

Full details, why each one is/isn't needed, and where to find real values in
the Supabase Dashboard: [`docs/backend-setup.md`](../../docs/backend-setup.md).
Quick reference:

**Required**: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWKS_URL`,
`SUPABASE_JWT_ISSUER`, `CORS_ORIGINS`, `PUBLIC_APP_URL`.

**Optional / legacy / currently unused** — safe to leave blank, never a
"missing required var" error: `SUPABASE_JWT_SECRET` (legacy HS256 fallback —
JWKS above is the current, preferred verification method), `DATABASE_URL`,
`DIRECT_URL` (no code path uses a direct Postgres connection — this backend
talks to Supabase exclusively over the REST API via `supabase-py`, never
Prisma or another ORM).

**Never** put `SUPABASE_SERVICE_ROLE_KEY` (or anything server-only) in
`apps/web`'s environment — the frontend only ever gets
`NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate # macOS/Linux

pip install -r requirements-dev.txt
cp .env.example .env         # then fill in Supabase values

uvicorn app.main:app --reload
```

API available at `http://localhost:8000`, docs at `http://localhost:8000/docs`.

## Test

```bash
pytest
```
