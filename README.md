# VIP Channel Management SaaS

Multi-tenant payment webhook ingestion service. FastAPI + SQLAlchemy 2.0 (async)
+ PostgreSQL, with tenant scoping enforced at the repository layer.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env
```

PowerShell:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
Copy-Item .env.example .env
```

## Database

Alembic owns the schema — the application never calls `create_all`. Both the app
and Alembic read the connection string from `DATABASE_URL`.

```bash
export DATABASE_URL="postgresql+asyncpg://vip:vip@localhost:5432/vip"
alembic upgrade head          # apply migrations
alembic revision --autogenerate -m "describe the change"
alembic downgrade -1          # roll back one revision
```

## Tenant isolation

Scoping is enforced in two independent layers, both keyed off the tenant bound
to the **Session** at the single place a session is created
(`get_tenant_session`):

1. **`with_loader_criteria`** appends `tenant_id = :tenant` to every ORM SELECT,
   including relationship loads. Queries are scoped whether or not the author
   remembered a `WHERE` clause.
2. **PostgreSQL row-level security** (migration `0002`) applies the same
   predicate inside the database, so it still holds when the ORM is bypassed —
   raw SQL, a Core `delete()`, a hand-written report. It fails closed: with no
   tenant published, `current_setting` returns NULL, the policy matches nothing,
   and a read returns zero rows rather than every row.

A `ContextVar` was considered and rejected. It removes the `tenant_id`
parameter but puts no predicate into the SQL, so it solves ergonomics rather
than safety — and it turns a signature that *cannot* be called without a tenant
into ambient state that is simply absent in every path with no HTTP request
behind it (a worker, a CLI script, a data migration).

> **The application must connect as an ordinary role.** PostgreSQL exempts
> superusers and `BYPASSRLS` roles from row policies. The test suite detects
> this and *skips* the RLS assertions with a loud reason rather than passing
> vacuously; `scripts/run-tests.ps1` provisions a `vip_app` role for exactly
> this reason.

## Request pipeline

```
TenantContextMiddleware  ->  routing  ->  body validation  ->  dependencies  ->  handler
        |
        +-- 401 missing X-Tenant-ID / 400 malformed  (public paths: /health, /docs, /redoc, /openapi.json)
```

Tenant identity is resolved exactly once, in the middleware, before routing.
Handlers read the validated `UUID` through the `get_tenant_id` dependency and
never touch the header themselves. Two consequences worth keeping:

* an unauthenticated request is rejected **before** body validation, so the
  payload contract is not disclosed to callers who have not identified
  themselves, and
* it is rejected **before** dependencies resolve, so no database session is
  opened for traffic that will be refused.

Both are locked in by tests in `tests/unit/step7/test_web_layer_and_guards.py`.

## Running the app

```bash
uvicorn app.main:app --reload
```

## Tests

Two backends, chosen by layer:

| Layer               | Database   | Why                                                     |
| ------------------- | ---------- | ------------------------------------------------------- |
| `tests/unit`        | SQLite     | No external service; keeps the inner loop fast.          |
| `tests/integration` | PostgreSQL | Same engine as production — real `uuid`/`numeric`/`tz`.  |
| `tests/e2e`         | PostgreSQL | Same reason.                                             |

Schema in **both** cases is built with `alembic upgrade head`, so drift between
the models and the migrations fails the test suite instead of the next deploy.

### Windows (PowerShell)

A helper script finds a locally installed PostgreSQL, creates the test database
if it is missing, and runs the suite. Docker is optional.

```powershell
.\scripts\run-tests.ps1 -UnitOnly            # no database needed
.\scripts\run-tests.ps1 -Password <pgpass>   # local PostgreSQL on :5432
.\scripts\run-tests.ps1 -UseDocker           # docker-compose on :5433
```

No PostgreSQL installed yet? `winget install -e --id PostgreSQL.PostgreSQL.16`

The admin password is asked for **once**, to create the `vip_app` role and the
test database. Every later run connects straight as `vip_app`.

### Changing the test role's password

```powershell
# interactive: psql prompts, so the password is never in your shell history
psql -U postgres -d postgres -c "\password vip_app"

# then tell the runner about it (add it to your PowerShell profile to persist)
$env:VIP_TEST_DB_PASSWORD = "<the new password>"
.\scripts\run-tests.ps1
```

If the role's stored password and `VIP_TEST_DB_PASSWORD` disagree, the runner
falls back to the admin account once and resets the role to match.

### Resetting the PostgreSQL admin password

Locked out of `postgres`? In an **Administrator** PowerShell:

```powershell
$hba = "C:\Program Files\PostgreSQL\16\data\pg_hba.conf"
Copy-Item $hba "$hba.bak"
(Get-Content $hba) -replace 'scram-sha-256|md5', 'trust' | Set-Content $hba
Restart-Service postgresql-x64-16

& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "\password postgres"

# Put it back. `trust` means any local process can connect as any role.
Copy-Item "$hba.bak" $hba -Force
Restart-Service postgresql-x64-16
```

By hand, if you prefer (note: PowerShell uses `$env:`, not `export`):

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://vip_app:vip@localhost:5432/vip_test"
pytest
```

### macOS / Linux

```bash
# unit layer only — no database needed
pytest -m "not postgres"

# full suite
docker compose -f docker-compose.test.yml up -d
export TEST_DATABASE_URL="postgresql+asyncpg://vip_app:vip@localhost:5433/vip_test"
pytest
```

Without `TEST_DATABASE_URL` the Postgres-backed tests **skip** rather than
silently downgrade to SQLite. In CI, set `TEST_REQUIRE_POSTGRES=1` so a missing
database is a hard failure and the layer can never quietly stop running.

## Layout

```
app/
  adapters/persistence/   SQLAlchemy models + tenant-scoped repositories
  adapters/web/           routers, middlewares, schemas
  core/                   database wiring, logging
  services/               application services
migrations/               Alembic revisions
scripts/run-tests.ps1     Windows test runner (finds PostgreSQL, creates the test DB)
tests/{unit,integration,e2e}/
```
