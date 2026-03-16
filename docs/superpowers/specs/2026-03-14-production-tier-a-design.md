# BitoGuard Production — Tier A Design Spec
**Target:** Small exchange, ≤10K users, single server, one analyst team
**Effort:** ~3–4 weeks (1 developer)
**Date:** 2026-03-14

---

## 1. Goals

Convert the hackathon demo into a single-server production system that is:
- Secure (authenticated API, HTTPS)
- Reliable (PostgreSQL instead of DuckDB for writes, scheduled pipeline)
- Complete (all frontend features wired up)
- Observable (structured logging, health checks)

Not in scope for Tier A: horizontal scaling, SSO, microservices, graph database.

---

## 2. Architecture Overview

```
Internet
  └── Nginx (HTTPS/443, Let's Encrypt)
        ├── /          → Next.js frontend (port 3000)
        └── /api/      → FastAPI core (port 8001)
                            ├── PostgreSQL (port 5432, same server)
                            ├── APScheduler (in-process cron)
                            └── Model artifacts (local filesystem)
```

All components run on a single EC2 instance (recommended: t3.medium or larger). PostgreSQL replaces DuckDB as the operational store. DuckDB is retained optionally for local analytics/ad-hoc queries against exported data.

---

## 3. Component Changes

### 3.1 Database — DuckDB → PostgreSQL

**Problem:** DuckDB cannot handle concurrent writes and is not safe for multi-process access.

**Solution:** Replace `DuckDBStore` with a `PostgresStore` using `psycopg2` (sync) or `asyncpg` (async). Use SQLAlchemy Core (not ORM) to keep the existing SQL patterns close to current code.

**Changes:**
- `bitoguard_core/db/store.py` — rewrite `DuckDBStore` as `PostgresStore` backed by SQLAlchemy engine with connection pool (`pool_size=10`, `max_overflow=20`)
- `bitoguard_core/db/schema.py` — convert `TableSpec` DDL from DuckDB SQL dialect to PostgreSQL (mostly compatible; adjust `TIMESTAMP` types, remove DuckDB-specific functions)
- `bitoguard_core/pipeline/` — all pipeline steps call `store.read_table()` / `store.replace_table()` — these become `SELECT` / `INSERT ... ON CONFLICT DO UPDATE` (upsert) in PostgreSQL
- Remove `duckdb` from dependencies, add `sqlalchemy`, `psycopg2-binary`
- Keep pandas DataFrames as the in-memory representation; use `pd.read_sql()` and `df.to_sql()` at the boundaries

**Schema namespaces:** PostgreSQL uses schemas (`raw`, `canonical`, `features`, `ops`) as DuckDB did. These map 1:1 to PostgreSQL schemas.

**Connection string:** Loaded from environment variable `DATABASE_URL=postgresql://user:pass@localhost:5432/bitoguard`.

### 3.2 Authentication — JWT + Static RBAC

**Problem:** Zero authentication. Any client can call any endpoint.

**Solution:** FastAPI middleware with JWT bearer tokens. Two static roles: `analyst` (read + decisions) and `admin` (all + pipeline triggers).

**Changes:**
- Add `bitoguard_core/auth/` module:
  - `jwt.py` — token creation/validation using `python-jose[cryptography]`
  - `middleware.py` — FastAPI `HTTPBearer` dependency, validates JWT, injects `current_user` into request state
  - `models.py` — `User` dataclass with `user_id`, `username`, `role`
- `bitoguard_core/api/main.py` — add `Depends(require_analyst)` or `Depends(require_admin)` to each endpoint
- Add `POST /auth/login` endpoint (username/password → JWT access token + refresh token)
- Add `POST /auth/refresh` endpoint
- Users stored in `ops.users` table (hashed passwords via `bcrypt`)
- **Frontend:** Add login page (`/login`). Store JWT in `httpOnly` cookie via Next.js API route. Add auth middleware in Next.js that redirects unauthenticated users.
- **Actor field:** Replace free-text `actor` in `DecisionRequest` with `current_user.username` injected server-side. Remove from request body.

**Roles:**
| Endpoint group | Required role |
|---|---|
| GET alerts, cases, reports | `analyst` |
| POST decisions | `analyst` |
| POST pipeline triggers (sync, train, score) | `admin` |
| GET model metrics, ops | `analyst` |

### 3.3 Pipeline Automation — APScheduler

**Problem:** All pipeline steps must be triggered manually.

**Solution:** Embed APScheduler into the FastAPI startup lifecycle. Define scheduled jobs that run the full pipeline nightly.

**Changes:**
- Add `bitoguard_core/scheduler/` module:
  - `jobs.py` — defines scheduled job functions (sync → normalize → graph → features → score → alert_engine)
  - `setup.py` — creates `BackgroundScheduler`, registers jobs, starts on FastAPI `startup` event, shuts down on `shutdown`
- Default schedule: nightly at 02:00 local time (configurable via env `PIPELINE_CRON_HOUR`, `PIPELINE_CRON_MINUTE`)
- Job status written to `ops.pipeline_runs` table (start time, end time, status, error message)
- Add `GET /ops/pipeline/runs` endpoint to expose run history to the frontend
- Manual trigger endpoints remain for on-demand runs

### 3.4 Graph Features — NetworkX Optimization

**Problem:** 6,000 BFS traversals per run (200 users × 30 days). Scales poorly.

**Solution:** Precompute graph features once per pipeline run (not per user per day). Cache results in the database. Batch all BFS traversals into a single graph construction pass.

**Changes:**
- `bitoguard_core/features/graph_features.py` — restructure to:
  1. Build the full entity graph once
  2. Run all BFS traversals in a single loop using `nx.all_pairs_shortest_path_length(graph, cutoff=4)` instead of per-node calls
  3. Write results to `features.graph_snapshots` table
- Replace `iterrows()` with vectorized pandas operations throughout (`itertuples()` where iteration is unavoidable, or `apply()`)
- `bitoguard_core/api/main.py` — `_build_graph_payload()` reads precomputed edges from DB instead of running live BFS per request

### 3.5 API Performance — SHAP Cache + Connection Singleton

**Problem:** SHAP `TreeExplainer` re-instantiated on every request. New DB connection per operation.

**Solution:**
- `bitoguard_core/services/explain.py` — cache the `TreeExplainer` instance as a module-level singleton, reloaded only when the model file changes (check mtime)
- `bitoguard_core/db/store.py` — `PostgresStore` uses a SQLAlchemy engine with connection pool (created once at startup, shared across requests)
- `bitoguard_core/api/main.py` — create a single `PostgresStore` instance at FastAPI startup via `app.state.store`, inject via `Depends(get_store)` instead of creating per-endpoint

### 3.6 Frontend — Wire Up Missing Features

**Problem:** Decision buttons exist in API but not in UI. No pagination. No user search.

**Changes:**
- `bitoguard_frontend/src/app/alerts/page.tsx` — add server-side pagination (`page` param, `limit=50`). Fetch page by page instead of all 200 at once.
- `bitoguard_frontend/src/components/diagnosis/` — add `DecisionPanel` component with buttons for allowed decisions (`confirm`, `dismiss`, `escalate`, `monitor`). Calls `postDecision()` from `api.ts` (already implemented). Shows action history.
- `bitoguard_frontend/src/app/users/page.tsx` — add free-text search input that filters users client-side (or adds `?q=` query param to API)
- `bitoguard_frontend/src/lib/api.ts` — add auth header injection from cookie, redirect to `/login` on 401

### 3.7 Security Hardening

- **HTTPS:** Nginx config updated to redirect HTTP→HTTPS, obtain cert via `certbot --nginx`
- **Docker:** Add non-root user in both Dockerfiles (`RUN adduser --system --no-create-home appuser && USER appuser`)
- **Secrets:** Move all secrets to environment variables loaded from a `.env` file not committed to git. Add `.env.example` template.
- **Structured logging:** Replace `print()` / bare `logging` calls with `structlog` JSON output. Log request ID, user ID, endpoint, latency on every request.
- **Health checks:** Add `GET /health` (liveness) and `GET /health/ready` (readiness — checks DB connectivity) endpoints

---

## 4. Data Model Changes

Two new tables added to `ops` schema:

```sql
-- ops.users
CREATE TABLE ops.users (
    user_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username    TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('analyst', 'admin')),
    created_at  TIMESTAMPTZ DEFAULT now(),
    last_login  TIMESTAMPTZ
);

-- ops.pipeline_runs
CREATE TABLE ops.pipeline_runs (
    run_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    triggered_by TEXT NOT NULL,  -- 'scheduler' or username
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    error_msg   TEXT,
    steps_completed TEXT[]
);
```

---

## 5. Dependencies Added

```
# Backend
sqlalchemy>=2.0
psycopg2-binary>=2.9
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
apscheduler>=3.10
structlog>=24.0

# Frontend (no new deps — auth via httpOnly cookie, existing fetch client)
```

---

## 6. Infrastructure

- **Server:** Single EC2 `t3.medium` (2 vCPU, 4GB RAM) — sufficient for ≤10K users
- **Database:** Amazon RDS `db.t3.micro` PostgreSQL 16, or self-hosted PostgreSQL on same EC2
- **TLS:** Let's Encrypt via certbot (auto-renews)
- **Process management:** Docker Compose with `restart: unless-stopped`
- **Backups:** RDS automated daily snapshots (if using RDS) or `pg_dump` cron if self-hosted

---

## 7. Migration Path from Hackathon

1. Spin up PostgreSQL (local Docker or RDS)
2. Run schema bootstrap (auto-creates all tables via `PostgresStore.__init__`)
3. Import existing CSV data via the simulator pipeline (sync → normalize → features → train → score)
4. Deploy with new Docker Compose referencing the live DB
5. Create initial admin user via CLI: `python -m bitoguard_core.cli create-user --admin`

---

## 8. What's Not Changed

- LightGBM + IsolationForest models — no changes needed
- SHAP explainability logic — only the caching wrapper changes
- Rule engine — no changes
- Composite scoring formula — no changes
- Mock API — no changes (still used as data source)
- Simulator — no changes
- Docker Compose structure — extended, not replaced
- Next.js frontend routing and proxy pattern — no changes

---

## 9. Success Criteria

- All API endpoints require valid JWT
- Pipeline runs nightly without manual intervention
- No DuckDB dependency in production runtime
- HTTPS on all traffic
- Decision buttons functional in UI
- Alerts paginated (no full-table fetches)
- SHAP explainer initialized once at startup
- Health check returns 200 within 500ms
