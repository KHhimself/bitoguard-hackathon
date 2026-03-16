# BitoGuard Production — Tier C Design Spec
**Target:** Large exchange, 500K+ users, distributed infrastructure, regulatory compliance
**Effort:** ~6+ months (dedicated infra + ML teams)
**Date:** 2026-03-14

---

## 1. Goals

Build an enterprise-grade, compliance-ready AML platform capable of:
- Real-time scoring (sub-second latency for individual user risk queries)
- Streaming pipeline (continuous ingestion, not nightly batch)
- Full SOC 2 Type II compliance audit trail
- Multi-tenant operation (multiple exchange clients or business units)
- Model governance (approval workflows, A/B testing, champion/challenger)
- 99.9% availability SLA

Tier C is a superset of Tier B. All Tier B changes apply; this spec describes what Tier C adds, replaces, or fundamentally restructures.

---

## 2. Architecture Overview

```
Internet
  └── AWS WAF → CloudFront → ALB
        ├── Next.js (ECS, auto-scaled, multi-AZ)
        └── API Gateway → Microservices (ECS/EKS)
              ├── scoring-service     ─── Real-time scoring API
              ├── case-service        ─── Case management + decisions
              ├── explain-service     ─── SHAP explanation + diagnosis
              ├── pipeline-service    ─── Pipeline orchestration API
              └── auth-service        ─── JWT, SSO, MFA, session mgmt

Data Layer:
  ├── PostgreSQL (RDS Multi-AZ)    ─── Operational data (cases, users, decisions)
  ├── Snowflake / BigQuery         ─── Analytics OLAP (features, scores, model metrics)
  ├── TigerGraph / Amazon Neptune  ─── Graph database (entity relationships)
  ├── Apache Kafka                 ─── Streaming event bus
  ├── Redis Cluster                ─── Cache + real-time state
  └── S3                          ─── Model artifacts, reports, audit archives

ML Platform:
  ├── Apache Airflow (MWAA)        ─── Pipeline DAG orchestration
  ├── MLflow                       ─── Experiment tracking, model registry
  └── Apache Flink / Spark         ─── Streaming feature computation
```

---

## 3. Microservices Decomposition

### Why Split?

The monolithic `bitoguard_core` FastAPI application mixes concerns: it serves API requests, runs the pipeline, manages ML models, and handles case workflows. At Tier C, these have conflicting requirements:
- **Scoring** needs low latency (<200ms P99) and horizontal auto-scaling
- **Pipeline** needs long-running CPU/memory resources without affecting API latency
- **Explain** is compute-intensive (SHAP) and can tolerate higher latency
- **Case management** needs strong consistency and audit logging

Splitting allows each service to scale, deploy, and fail independently.

### 3.1 scoring-service

**Responsibility:** Real-time user risk score lookup and on-demand re-scoring.

**Stack:** FastAPI, Python, Redis (cache), Snowflake (feature reads)

**Key endpoints:**
- `GET /scores/{user_id}` — returns cached score with TTL, triggers async re-score if stale
- `POST /scores/batch` — batch scoring for a list of user IDs
- `GET /scores/{user_id}/features` — returns the feature vector used for the latest score

**Scaling:** 4–20 ECS tasks, auto-scaling on P95 latency. Independent from other services.

**Caching strategy:**
- Score cached in Redis with 1-hour TTL
- Feature vector cached in Redis with 6-hour TTL
- LightGBM model loaded once at startup from MLflow model registry, reloaded on version change signal (Redis pub/sub)

### 3.2 case-service

**Responsibility:** Alert lifecycle, case decisions, analyst assignment, action history.

**Stack:** FastAPI, Python, PostgreSQL (strong consistency required for decisions)

**Key endpoints:** All `/alerts`, `/cases`, `/decisions` endpoints from current `main.py`

**Audit trail:** Every state change (decision, assignment, escalation) writes an immutable record to `ops.audit_log` with user, timestamp, before/after state. Audit log is append-only (no UPDATE/DELETE).

**Compliance features:**
- 7-year audit log retention (S3 Glacier archive after 90 days)
- Cryptographic hash chaining on audit log records (each record hashes the previous — tamper-evident)
- `GET /audit/{case_id}/history` — full immutable decision trail for regulatory export

### 3.3 explain-service

**Responsibility:** SHAP explanations, risk diagnosis reports, recommended actions.

**Stack:** FastAPI, Python, dedicated GPU/CPU task pool

**Key endpoints:** `/diagnosis/{user_id}`, `/explain/{user_id}`

**Changes from current:**
- Explanation requests queued via Redis task queue (Celery) — async, not blocking
- Pre-compute explanations for all high/critical alerts after each scoring run
- Persist explanation JSONs to S3 + reference in `ops.alerts.report_s3_path` (fixes the current `report_path=None` gap)
- `GET /diagnosis/{user_id}` returns pre-computed report from S3 if available, triggers fresh computation otherwise

### 3.4 pipeline-service

**Responsibility:** Pipeline orchestration API (trigger, status, history). Delegates actual work to Airflow.

**Stack:** FastAPI, Python, Airflow REST API client

**Key endpoints:**
- `POST /pipeline/trigger` — triggers Airflow DAG run
- `GET /pipeline/runs` — lists DAG runs with status from Airflow API
- `GET /pipeline/runs/{run_id}/logs` — streams Airflow task logs

### 3.5 auth-service

**Responsibility:** Authentication, authorization, MFA, session management.

**Stack:** FastAPI, Python, PostgreSQL, Redis

**Beyond Tier B:**
- TOTP-based MFA (Google Authenticator / Authy) enforced for all users
- Hardware key support (WebAuthn/FIDO2) for admin accounts
- Session management with absolute timeout (8 hours) and idle timeout (30 minutes)
- IP allowlist per user/team (restrict analysts to office VPN range)
- Login anomaly detection (new country, unusual hour → require MFA re-verify)
- `GET /auth/sessions` — list active sessions, allow remote logout

---

## 4. Streaming Pipeline — Apache Kafka + Flink

**Replaces:** Tier B nightly Celery batch pipeline

**Why:** At 500K+ users with continuous transaction ingestion, nightly batch creates a 24-hour detection lag. Streaming reduces detection latency to minutes.

### Architecture

```
Exchange Core System
  └── Kafka Producer → Kafka Topics
        ├── topic: transactions.fiat
        ├── topic: transactions.crypto
        ├── topic: user.events (login, device, IP)
        └── topic: kyc.events

Apache Flink (streaming processor)
  ├── Consumes all Kafka topics
  ├── Computes streaming features (rolling windows: 1h, 6h, 24h, 7d)
  ├── Writes features to Snowflake (micro-batch, 5-minute windows)
  └── Publishes scoring trigger events to Kafka topic: scoring.triggers

scoring-service (consumer)
  └── Consumes scoring.triggers → fetches features → runs model → publishes to:
        ├── Kafka topic: risk.scores (for downstream consumers)
        └── Redis (for API cache)

alert-engine (consumer)
  └── Consumes risk.scores → creates alerts for high/critical users → PostgreSQL
```

### Flink Jobs

- `bitoguard_streaming/jobs/fiat_velocity.py` — rolling sum of fiat transactions per user
- `bitoguard_streaming/jobs/night_activity.py` — event count in hours 0–5 rolling 24h
- `bitoguard_streaming/jobs/device_fingerprint.py` — new device detection with session join
- `bitoguard_streaming/jobs/graph_updates.py` — incremental edge updates to TigerGraph on new device/wallet/bank linkage

### Batch Fallback

Apache Airflow DAG still runs nightly for:
- Full feature recomputation (correctness check on streaming features)
- Model retraining (using Snowflake feature store)
- Historical backfill when new features are added

---

## 5. Graph Database — TigerGraph / Amazon Neptune

**Replaces:** Tier B Apache AGE

**Why:** At 500K+ users with millions of entity relationships, graph traversal within PostgreSQL (even with AGE) becomes a bottleneck. Dedicated graph databases use index-free adjacency for O(1) hop traversal regardless of graph size.

**Choice:**
- **TigerGraph** — best performance for deep multi-hop traversal, native GSQL language, enterprise support
- **Amazon Neptune** — managed, Gremlin/SPARQL/openCypher, easier ops, less raw performance

**Schema (TigerGraph GSQL):**

```gsql
CREATE VERTEX User (PRIMARY_ID user_id STRING)
CREATE VERTEX Device (PRIMARY_ID device_id STRING)
CREATE VERTEX BankAccount (PRIMARY_ID account_id STRING)
CREATE VERTEX Wallet (PRIMARY_ID address STRING, is_blacklisted BOOL)
CREATE VERTEX IPAddress (PRIMARY_ID ip STRING)

CREATE DIRECTED EDGE USES_DEVICE (FROM User, TO Device, first_seen DATETIME, last_seen DATETIME)
CREATE DIRECTED EDGE USES_BANK (FROM User, TO BankAccount)
CREATE DIRECTED EDGE TRANSFERS_TO (FROM User, TO Wallet, total_amount DOUBLE)
CREATE DIRECTED EDGE CONNECTS_FROM (FROM User, TO IPAddress)
```

**Queries:**
- 2-hop shared device: `GSQL query shared_device_ring(user_id)` — returns all users sharing any device within 2 hops
- Blacklist proximity: `GSQL query blacklist_proximity(user_id, cutoff=2)` — shortest path to any blacklisted wallet
- Component size: `GSQL query connected_component_size(user_id)` — number of users in same connected component

**Sync:** Kafka consumer writes new edges to TigerGraph in near-real-time. Full sync runs weekly.

---

## 6. ML Platform — MLflow + Model Governance

**Adds to Tier B S3 model storage:**

### MLflow Model Registry

- All model training runs logged to MLflow (metrics, parameters, artifacts)
- Models go through lifecycle: `Staging → Production → Archived`
- Promotion from Staging to Production requires approval from a `senior_analyst` or `admin` role
- `explain-service` and `scoring-service` load the model tagged `Production` from MLflow registry

### Champion/Challenger

- `ops.model_experiments` table tracks A/B assignments per user
- New model variant (challenger) scored for 10% of users
- MLflow experiment tracks challenger vs champion performance
- Analyst dashboard (Model Ops view) shows live champion/challenger metric comparison
- Promotion triggers Kafka event → services reload challenger as new champion

### Model Monitoring + Drift Detection

- `bitoguard_streaming/jobs/drift_monitor.py` — Flink job computing:
  - Feature distribution drift (PSI — Population Stability Index) per feature per day
  - Score distribution drift (KL divergence between last 7-day and baseline)
  - Alert written to `ops.model_alerts` when PSI >0.2 or score distribution shifts >15%
- Automatic retraining trigger: Airflow DAG triggered when drift threshold exceeded
- Retraining creates a new MLflow run (Staging), requires human approval to promote

---

## 7. Compliance — SOC 2 Type II

### Audit Trail

- All API requests logged to `ops.request_log` (user, endpoint, parameters, IP, timestamp, response code)
- All data access logged (which analyst viewed which user's data)
- Immutable audit log with hash chaining (see case-service section)
- 7-year retention with S3 Glacier archiving

### Access Control

- MFA enforced for all users (no exceptions)
- Principle of least privilege: analysts only see alerts assigned to their team
- Admin access requires MFA re-verification for sensitive operations
- IP allowlist enforced at auth-service level

### Data Privacy

- PII fields (phone, email, bank account numbers) encrypted at rest using AWS KMS customer-managed keys
- Field-level encryption: only decrypted when accessed by authorized analyst, access logged
- Right-to-erasure: `DELETE /users/{user_id}/pii` anonymizes PII while retaining transaction records

### Penetration Testing

- Annual third-party pentest required for SOC 2
- OWASP Top 10 coverage in security test suite
- Dependency vulnerability scanning in CI (Snyk or Dependabot)

---

## 8. Infrastructure — Kubernetes + Service Mesh

- **Compute:** Amazon EKS (Kubernetes). Each microservice deployed as a K8s Deployment with HPA.
- **Service mesh:** AWS App Mesh or Istio — mutual TLS between services, circuit breaking, traffic shaping for champion/challenger routing
- **Secrets:** AWS Secrets Manager + Kubernetes External Secrets Operator
- **VPC:** Services in private subnets. Only ALB is internet-facing. NAT Gateway for outbound.
- **WAF:** AWS WAF in front of CloudFront — rate limiting, IP reputation, bot detection
- **HSM:** AWS CloudHSM for cryptographic key management (JWT signing, audit log hashing)
- **Observability:** Datadog or New Relic — APM tracing across microservices, dashboards, alerting
- **Disaster recovery:** Multi-region active-passive. RTO: 1 hour, RPO: 15 minutes.

---

## 9. New Dependencies

```
# Streaming
apache-flink>=1.18       (Python API)
confluent-kafka>=2.3

# ML Platform
mlflow>=2.10
evidently>=0.4           (drift detection)

# Graph
tigergraph-python>=3.9   or
gremlinpython>=3.7       (Neptune)

# Compliance
cryptography>=42.0       (field-level encryption)
boto3>=1.34              (KMS)

# Infrastructure
# - Amazon EKS, MSK (Kafka), MWAA (Airflow), Neptune/TigerGraph
# - Snowflake or BigQuery connector
# - AWS WAF, CloudHSM, CloudFront
# - Datadog or New Relic
```

---

## 10. Migration Path from Tier B

1. Deploy Kafka (MSK), create topics, deploy Flink jobs alongside existing batch pipeline
2. Stand up MLflow, migrate model artifacts from S3 to MLflow registry
3. Deploy microservices alongside monolith (strangler fig pattern) — route traffic gradually
4. Stand up TigerGraph/Neptune, migrate graph from AGE
5. Migrate from ECS to EKS
6. Enable streaming pipeline, reduce Airflow batch to weekly full-refresh
7. Implement SOC 2 controls (audit log, field encryption, MFA)
8. Decommission monolith

---

## 11. Success Criteria

- Risk score API P99 latency <200ms at 1000 req/s
- Pipeline detection lag <10 minutes (streaming)
- Model promotion requires explicit approval (no accidental deploys)
- Drift detection triggers retraining within 24 hours of threshold breach
- Full SOC 2 audit trail: every data access logged and tamper-evident
- 99.9% availability (≤8.7 hours downtime/year)
- Zero-trust network: all inter-service communication via mutual TLS
