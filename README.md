# BitoGuard — Exchange-Centric AML Risk Detection System

BitoGuard is a production-minded Anti-Money Laundering (AML) / fraud-risk detection system built over the BitoPro AWS-event data model. It implements a complete 6-module architecture for detecting, explaining, and monitoring suspicious activity on a cryptocurrency exchange.

## Architecture Overview

| Module | Description | Key Files |
|--------|-------------|-----------|
| M1: Rules | 11 deterministic AML rules, severity-weighted scoring | `bitoguard_core/models/rule_engine.py` |
| M2: Statistical | Peer-deviation features, cohort percentile ranks, rolling windows | `bitoguard_core/features/build_features.py` |
| M3: Supervised | LightGBM with leakage-safe temporal splits, P@K, calibration | `bitoguard_core/models/train.py`, `validate.py` |
| M4: Anomaly | IsolationForest novelty detection, anomaly score + type | `bitoguard_core/models/anomaly.py` |
| M5: Graph | NetworkX heterogeneous graph (IP/wallet/user), blacklist proximity | `bitoguard_core/features/graph_features.py` |
| M6: Ops | SHAP case reports, incremental refresh, drift detection, AWS prep | `bitoguard_core/services/`, `pipeline/refresh_live.py` |

## Quick Start

```bash
# Start everything with Docker
cp deploy/.env.compose.example .env
docker compose up --build

# Or run locally
cd bitoguard_core
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the backend test suite
make test

# Full pipeline
make sync && make features && make train && make score && make drift

# API server
PYTHONPATH=. uvicorn api.main:app --reload --port 8001
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| `bitoguard_core` | 8001 | FastAPI — pipeline, model, alerts, graph, metrics |
| `bitoguard_frontend` | 3000 | Next.js — alerts dashboard, model ops, graph explorer |

### Frontend

```bash
cd bitoguard_frontend && npm install && npm run dev
# Open http://localhost:3000
```

## Makefile Targets (run from `bitoguard_core/`)

```bash
make test        # Run all 124 tests
make sync        # Sync live BitoPro data
make features    # Build feature snapshots + graph features
make train       # Train LightGBM + IsolationForest
make evaluate    # Holdout evaluation (P/R/F1/P@K/calibration)
make ablation    # Module ablation study
make refresh     # Incremental refresh (watermark-bounded)
make score       # Score latest snapshot → alerts
make drift       # Feature distribution drift check
make cases       # Generate SHAP case reports
make docker-build
make docker-up
```

## API Endpoints (bitoguard_core, port 8001)

| Endpoint | Description |
|----------|-------------|
| `GET /healthz` | Health check |
| `POST /pipeline/sync` | Trigger data sync |
| `POST /features/rebuild` | Rebuild feature snapshots |
| `POST /model/train` | Train + evaluate model |
| `POST /model/score` | Score latest snapshot |
| `GET /alerts` | List alerts (paginated) |
| `GET /alerts/{id}/report` | Risk diagnosis with SHAP + graph |
| `POST /alerts/{id}/decision` | Case decision |
| `GET /users/{id}/360` | User 360 view |
| `GET /users/{id}/graph` | Graph neighborhood (1-2 hops) |
| `GET /metrics/model` | Full validation report (P@K, calibration, FI) |
| `GET /metrics/threshold` | Threshold sensitivity table |
| `GET /metrics/drift` | Feature drift health (auto-refreshes 60s in UI) |

## Documentation

| Document | Location |
|----------|----------|
| Local runbook | `docs/RUNBOOK_LOCAL.md` |
| AWS runbook | `docs/RUNBOOK_AWS.md` |
| Evaluation report | `docs/EVALUATION_REPORT.md` |
| Feature dictionary | `docs/FEATURE_DICTIONARY.md` |
| Rule book | `docs/RULEBOOK.md` |
| Graph schema | `docs/GRAPH_SCHEMA.md` |
| Model card | `docs/MODEL_CARD.md` |
| Data contract | `docs/DATA_CONTRACT.md` |
| Release readiness checklist | `docs/RELEASE_READINESS_CHECKLIST.md` |

## Validation

```
make test-quick
cd bitoguard_frontend && npm run lint && npm run build
```

## AWS Deployment

Infrastructure artifacts are in `infra/aws/` and `scripts/`:

```bash
# Requires AWS credentials + ECR/ECS setup:
./scripts/build_and_push.sh    # Build + push images to ECR
./scripts/deploy_aws.sh        # Register task defs + update ECS services
```

See `docs/RUNBOOK_AWS.md` and `docs/RELEASE_READINESS_CHECKLIST.md`.
