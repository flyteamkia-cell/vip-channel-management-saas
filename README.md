# VIP Channel Management SaaS

Multi-tenant payment webhook ingestion service. FastAPI + SQLAlchemy 2.0 (async)
+ PostgreSQL, with tenant scoping enforced at the repository layer.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[test]"
cp .env.example .env
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
tests/{unit,integration,e2e}/
```
