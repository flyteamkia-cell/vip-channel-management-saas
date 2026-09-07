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

By hand, if you prefer (note: PowerShell uses `$env:`, not `export`):

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://postgres:<pgpass>@localhost:5432/vip_test"
pytest
```

### macOS / Linux

```bash
# unit layer only — no database needed
pytest -m "not postgres"

# full suite
docker compose -f docker-compose.test.yml up -d
export TEST_DATABASE_URL="postgresql+asyncpg://vip:vip@localhost:5433/vip_test"
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
