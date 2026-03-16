# BitoGuard Production — Tier B Design Spec
**Target:** Mid-size exchange, 10K–500K users, multiple analyst teams
**Effort:** ~2–3 months (small team: 2–3 developers)
**Date:** 2026-03-14

---

## 1. Goals

Build a horizontally scalable, team-ready AML platform that can:
- Handle concurrent analyst workflows across multiple teams
- Process 100K+ user scoring runs in under 30 minutes
- Support SSO login (enterprise identity providers)
- Provide real-time alert notifications
- Survive infrastructure failures (HA database, retryable jobs)

Tier B is a superset of Tier A. All Tier A changes apply; this spec describes what Tier B adds or replaces.

---

## 2. Architecture Overview

```
Internet
  └── AWS ALB (HTTPS/443, ACM cert)
        ├── /          → Next.js (ECS service, 2+ tasks)
        └── /api/      → FastAPI (ECS service, 2+ tasks)
                            ├── RDS PostgreSQL Multi-AZ (primary + standby)
                            │     └── PgBouncer (connection pooling sidecar)
                            ├── Redis (ElastiCache) — task queue + cache
                            │     ├── Celery broker (pipeline task queue)
                            │     └── API response cache (scores, reports)
                            ├── Celery Workers (ECS service, auto-scaling)
                            │     └── Pipeline tasks: sync, features, train, score
                            └── Model artifacts (S3 bucket)

Graph:
  └── Apache AGE (PostgreSQL extension) — graph queries in SQL
      or Neo4j (separate ECS service)
```

---

## 3. Component Changes vs Tier A

### 3.1 Database — PostgreSQL + PgBouncer + Read Replicas

**Replaces:** Tier A single PostgreSQL instance

**Changes:**
- **Primary:** RDS PostgreSQL Multi-AZ (`db.t3.large`). Automatic failover to standby replica.
- **Read replica:** RDS read replica for analytics queries (feature reads, report generation). FastAPI routes write operations to primary, reads to replica.
- **PgBouncer:** Connection pooler deployed as ECS sidecar or standalone container. Reduces connection overhead under concurrent load. `pool_mode=transaction`, `max_client_conn=500`.
- `bitoguard_core/db/store.py` — add `write_engine` and `read_engine` as separate SQLAlchemy engines. Write operations (pipeline, decisions) use `write_engine`; read operations (API responses) use `read_engine`.

### 3.2 Authentication — JWT + DB-Backed RBAC + SSO

**Replaces:** Tier A static RBAC with two hardcoded roles

**Changes:**
- **DB-backed roles:** Roles stored in `ops.roles` and `ops.user_roles` tables. New roles can be created without code changes: `analyst`, `senior_analyst`, `team_lead`, `admin`, `readonly`.
- **Permissions table:** Fine-grained permissions (`ops.permissions`) with `resource` + `action` pairs (e.g., `alerts:read`, `cases:write`, `pipeline:trigger`).
- **SSO via SAML 2.0 / OIDC:** Add `python-saml` or `authlib` for identity provider integration. Supports Okta, Azure AD, Google Workspace. User accounts auto-provisioned on first SSO login.
- **Token refresh:** Sliding window refresh tokens stored in Redis with TTL. Revocable on logout or admin action.
- `bitoguard_core/auth/` — expanded with `saml.py`, `oidc.py`, `permissions.py`

**New roles schema:**
```sql
CREATE TABLE ops.roles (
    role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE ops.permissions (
    permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id UUID REFERENCES ops.roles(role_id),
    resource TEXT NOT NULL,   -- 'alerts', 'cases', 'pipeline', 'models'
    action TEXT NOT NULL      -- 'read', 'write', 'trigger', 'admin'
);

CREATE TABLE ops.user_roles (
    user_id UUID REFERENCES ops.users(user_id),
    role_id UUID REFERENCES ops.roles(role_id),
    team_id UUID REFERENCES ops.teams(team_id),  -- optional team scope
    PRIMARY KEY (user_id, role_id)
);
```

### 3.3 Pipeline Automation — Celery + Redis

**Replaces:** Tier A APScheduler (in-process)

**Why:** APScheduler runs inside the FastAPI process — it cannot scale horizontally (two API instances would both schedule the same job), cannot retry failed tasks, and cannot distribute work across workers.

**Changes:**
- Add `bitoguard_core/tasks/` module:
  - `celery_app.py` — Celery app configured with Redis broker (`CELERY_BROKER_URL`) and Redis result backend
  - `pipeline_tasks.py` — Celery tasks: `sync_task`, `normalize_task`, `graph_task`, `features_task`, `train_task`, `score_task`, `alert_task`
  - `schedules.py` — Celery Beat schedule (replaces APScheduler). Beat runs as a separate ECS task.
- Pipeline tasks are chained: `sync_task.si() | normalize_task.si() | ... | alert_task.si()`
- Each task writes its status to `ops.pipeline_runs`. Failed tasks are retried up to 3 times with exponential backoff.
- Manual triggers via API call `task.delay()` instead of direct function call.
- Add `GET /ops/tasks/{task_id}` endpoint to poll task status from Celery result backend.
- **Dead-letter queue:** Failed tasks after max retries written to `ops.pipeline_failures` for manual inspection.

**New ECS services:**
- `bitoguard-celery-worker` — runs `celery -A bitoguard_core.tasks.celery_app worker`
- `bitoguard-celery-beat` — runs `celery -A bitoguard_core.tasks.celery_app beat`

### 3.4 Graph Computation — Apache AGE (Graph DB in PostgreSQL)

**Replaces:** Tier A NetworkX optimization

**Why:** At 100K+ users, in-memory NetworkX graph becomes too large. Apache AGE adds openCypher graph query support directly to PostgreSQL — no separate graph database to operate.

**Changes:**
- Enable `age` extension in PostgreSQL: `CREATE EXTENSION age;`
- `bitoguard_core/pipeline/rebuild_edges.py` — instead of building a NetworkX graph, write edges to AGE graph using Cypher `MERGE` statements
- `bitoguard_core/features/graph_features.py` — replace Python BFS with AGE Cypher queries:
  ```cypher
  MATCH (u:User {id: $user_id})-[:SHARES*1..2]-(neighbor)
  RETURN neighbor.id, length(path) as hops
  ```
- `bitoguard_core/api/main.py` — `_build_graph_payload()` queries AGE directly; no in-memory graph construction
- Graph updates are incremental: new edges `MERGE`d without full rebuild

**Fallback:** If AGE adoption is a risk, Neo4j CE (self-hosted) is an alternative. It adds an ECS service but has better tooling and Cypher maturity.

### 3.5 API — Multiple Replicas + Redis Cache

**Replaces:** Tier A single FastAPI instance with module-level cache

**Changes:**
- FastAPI deployed as 2+ ECS tasks behind ALB. Stateless — all state in PostgreSQL/Redis.
- `bitoguard_core/cache/` — Redis cache layer using `redis-py`:
  - `cache.py` — `get_cached()` / `set_cached()` with configurable TTL
  - Cache keys: `score:{user_id}:{date}` (TTL 1h), `report:{user_id}` (TTL 15m), `model:metadata` (TTL 24h)
- SHAP explainer cache: Stored as pickled bytes in Redis (shared across replicas). Invalidated when model artifact changes (S3 ETag check).
- `bitoguard_core/api/main.py` — inject Redis client via `Depends(get_redis)`, check cache before DB on all read endpoints.

### 3.6 Model Artifacts — S3

**Replaces:** Local filesystem model storage

**Changes:**
- `bitoguard_core/models/common.py` — `save_model()` writes to S3 (`s3://bitoguard-models/artifacts/{model_type}/{version}.pkl`), `load_model()` downloads from S3 (cached locally in `/tmp`)
- Model versions tracked in `ops.model_versions` table with S3 path, training metrics, and `is_active` flag
- `GET /ops/models` API returns version history with metrics for the Model Ops view
- Old model versions retained in S3 for rollback

### 3.7 Frontend — Real-Time + Team Features

**Adds to Tier A frontend:**
- **Real-time alert feed:** Server-Sent Events (SSE) endpoint `GET /alerts/stream`. Frontend connects on load, receives new alert events as they're created by `alert_engine`. Next.js `EventSource` client with reconnect logic.
- **Team workspace:** Analysts see only alerts assigned to their team. Team assignment stored in `ops.cases` (`team_id` column). Admin can reassign.
- **Role-based views:** Navigation items and action buttons rendered conditionally based on JWT claims. Pipeline trigger button only shown to `admin` role.
- **Notification badge:** Alert count in nav badge, updated via SSE.
- All Tier A frontend fixes included (decision UI, pagination, user search).

### 3.8 Infrastructure — ECS + RDS Multi-AZ

- **Compute:** AWS ECS Fargate (serverless containers). No EC2 management.
  - `bitoguard-api`: 2 tasks, `1 vCPU / 2GB`, auto-scaling on CPU >70%
  - `bitoguard-frontend`: 2 tasks, `0.5 vCPU / 1GB`
  - `bitoguard-celery-worker`: 1–4 tasks, auto-scaling on queue depth
  - `bitoguard-celery-beat`: 1 task (singleton)
- **Database:** RDS PostgreSQL 16 Multi-AZ, `db.t3.large`. Automated backups, 7-day retention.
- **Cache/Queue:** ElastiCache Redis 7, `cache.t3.micro` (cluster mode disabled for simplicity).
- **Load balancer:** ALB with ACM-managed HTTPS cert. Path-based routing to frontend and API target groups.
- **Secrets:** AWS Secrets Manager for DB credentials, JWT secret, SSO client secrets. Loaded at ECS task startup via `aws secretsmanager get-secret-value`.
- **Logging:** CloudWatch Logs for all ECS tasks. Structured JSON logs from `structlog`.
- **Monitoring:** CloudWatch dashboards for API latency, error rate, pipeline run success/failure, queue depth.
- **CI/CD:** GitHub Actions workflow: test → build Docker image → push to ECR → update ECS service.

---

## 4. New Dependencies

```
# Backend (in addition to Tier A)
celery[redis]>=5.3
redis>=5.0
authlib>=1.3          # OIDC/OAuth2
python-saml>=3.0      # SAML SSO
boto3>=1.34           # S3, Secrets Manager

# Infrastructure
# - Apache AGE (PostgreSQL extension, installed on RDS custom parameter group)
# - ElastiCache Redis
# - AWS ALB + ACM
# - AWS Secrets Manager
# - Amazon ECR (container registry)
# - GitHub Actions (CI/CD)
```

---

## 5. Migration Path from Tier A

1. Provision ElastiCache Redis
2. Migrate from APScheduler → Celery Beat (deploy beat + worker ECS tasks)
3. Enable AGE extension, migrate entity graph from NetworkX snapshots to AGE
4. Add read replica, update `PostgresStore` to route reads/writes
5. Add SSO (can run alongside username/password auth during transition)
6. Move model artifacts to S3
7. Deploy additional API replicas, wire up Redis cache
8. Add SSE endpoint and frontend real-time feed

---

## 6. Success Criteria

- 500 concurrent analysts without API degradation
- Pipeline completes in <30 min for 100K users
- Failed pipeline tasks auto-retry and alert on repeated failure
- SSO login works with Okta/Azure AD
- Live alert feed delivers new alerts within 5 seconds
- Model artifacts versioned and rollback-capable in <5 minutes
- Zero-downtime deploys via ECS rolling update
