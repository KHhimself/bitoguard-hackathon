# Local Runbook

This runbook covers running BitoGuard locally for development, testing, and demo purposes.

## Quick Reference

Most operations are available as single-command Makefile targets from the project root:

```bash
make help          # Show all targets
make setup         # Install Python dependencies
make test          # Run 61-test suite
make sync          # Full data sync from live API
make features      # Rebuild feature snapshots
make train         # Train LightGBM + IsolationForest
make evaluate      # Temporal holdout evaluation
make ablation      # Module ablation study
make refresh       # Incremental live refresh
make score         # Score latest snapshot + alerts
make drift         # Feature drift detection
make cases         # Generate analyst case reports
make docker-build  # Build Docker images
make docker-up     # Start full stack
```

## Prerequisites

- Python 3.12 with the `bitoguard_core` virtual environment activated
- Node.js 20+ for the frontend
- Docker + Docker Compose for containerized operation
- Network access to `https://aws-event-api.bitopro.com` for live data sync

## Directory Structure

```
bitoguard-hackathon/
├── bitoguard_core/          # FastAPI backend + pipeline
│   ├── .venv/               # Python virtual environment
│   ├── artifacts/           # DuckDB, model pickles, reports
│   ├── api/                 # FastAPI handlers
│   ├── pipeline/            # ETL: sync, normalize, rebuild, refresh
│   ├── features/            # Feature builders (graph + tabular)
│   ├── models/              # Train, anomaly, validate, score, rules
│   ├── services/            # Alert engine, explain, diagnosis
│   └── tests/               # pytest suite
├── bitoguard_frontend/      # Next.js 16 App Router UI
├── bitoguard_mock_api/      # Optional offline CSV-backed source adapter
├── bitoguard_sim_output/    # Optional simulation CSV fixtures
└── compose.yaml             # Docker Compose stack
```

## Quick Start: Docker Compose (Recommended)

```bash
# Start backend + frontend (uses live BitoPro API as source)
docker compose up --build

# With mock API for offline demo
docker compose --profile sync up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8001
- API docs: http://localhost:8001/docs

## Manual Local Development

### Backend Setup

```bash
cd bitoguard_core
python -m venv .venv  # or: uv venv .venv
. .venv/bin/activate
pip install -r requirements.txt  # or: uv pip install -r requirements.txt

# Run backend API
PYTHONPATH=. uvicorn api.main:app --reload --port 8001
```

### Frontend Setup

```bash
cd bitoguard_frontend
npm install
cp .env.example .env.local  # Set BITOGUARD_INTERNAL_API_BASE=http://127.0.0.1:8001
npm run dev  # Runs on :3000
```

## Full Pipeline Execution

### Step 1: Data Sync

Sync data from the live BitoPro PostgREST API into local DuckDB:

```bash
cd bitoguard_core && . .venv/bin/activate
PYTHONPATH=. python pipeline/sync.py --full
```

This runs the full pipeline:
1. `sync_source.py` — fetches live data into `raw.*` tables
2. `load_oracle.py` — loads train labels into `ops.oracle_user_labels`
3. `normalize.py` — deduplicates and normalizes into `canonical.*` tables
4. `rebuild_edges.py` — rebuilds `canonical.entity_edges` graph

Expected row counts after sync:
- users: ~63,000+
- login_events: ~576,000+
- fiat_transactions: ~195,000+
- trade_orders: ~271,000+
- crypto_transactions: ~239,000+
- known_blacklist_users: ~1,600+
- crypto_wallets: ~105,000+

### Step 2: Build Features

```bash
PYTHONPATH=. python features/graph_features.py    # Graph features (slow on full dataset)
PYTHONPATH=. python features/build_features.py    # Tabular features
```

Or via API:
```bash
curl -X POST http://localhost:8001/features/rebuild
```

### Step 3: Train Models

```bash
PYTHONPATH=. python models/train.py       # LightGBM
PYTHONPATH=. python models/anomaly.py    # IsolationForest
PYTHONPATH=. python models/validate.py   # Validation report
```

Or via API:
```bash
curl -X POST http://localhost:8001/model/train
```

### Step 4: Score Latest Snapshot

```bash
PYTHONPATH=. python models/score.py
```

Or via API:
```bash
curl -X POST http://localhost:8001/model/score
```

### Step 5: Incremental Live Refresh

After the initial sync + train cycle, use incremental refresh for ongoing updates:

```bash
PYTHONPATH=. python pipeline/refresh_live.py
```

This:
1. Checks the watermark (`ops.refresh_state`)
2. If new events exist, derives affected user IDs
3. Rebuilds features only for affected users at the latest snapshot date
4. Scores and generates alerts (no retraining)

Expected runtime: ~10-30 seconds (incremental, not full rebuild).

## Running Tests

```bash
# Full test suite (61 tests: unit + integration + smoke + drift + rule engine)
cd bitoguard_core && . .venv/bin/activate
PYTHONPATH=. pytest tests/ -v

# Quick run (same tests, less output)
PYTHONPATH=. pytest tests/ -q

# Or via Makefile from project root:
make test
```

Expected: **61 tests pass** across 4 test files:
- `test_rule_engine.py`: 33 tests — all 11 rules, trigger + no-trigger cases
- `test_model_pipeline.py`: 15 tests — temporal splits, refresh, drift detection
- `test_source_integration.py`: 6 tests — canonicalization, sync lifecycle
- `test_smoke.py`: 5 tests — API smoke, alert/case lifecycle

## Module Ablation Study

Run an ablation to measure each module's contribution to detection performance:

```bash
cd bitoguard_core && . .venv/bin/activate
PYTHONPATH=. python scripts/ablation_study.py

# Or via Makefile:
make ablation
```

Output: prints a markdown table + saves `artifacts/ablation_report.json`.

Key results from last run (holdout: 15,672 rows, 9,648 positives):

| Module | Precision | Recall | F1 | PR-AUC |
|---|---|---|---|---|
| Rules only | 0.995 | 0.750 | 0.855 | 0.964 |
| + Supervised | 0.998 | 1.000 | 0.999 | 1.000 |
| + Anomaly | 0.998 | 1.000 | 0.999 | 0.998 |
| + Graph | 0.998 | 1.000 | 0.999 | 0.999 |
| Full system | 0.999 | 0.917 | 0.956 | 0.999 |

## Generating Analyst Case Reports

```bash
# Generate 5 SHAP-explained case reports for top risk users → examples/
cd bitoguard_core && . .venv/bin/activate
python -c "
import json, shap, pandas as pd
from pathlib import Path
from config import load_settings
from db.store import DuckDBStore
from models.common import encode_features, feature_columns, load_pickle

s = load_settings()
store = DuckDBStore(s.db_path)
models_dir = s.artifact_dir / 'models'
lgbm_pkl = sorted(models_dir.glob('lgbm_*.pkl'))[-1]
meta = json.loads(lgbm_pkl.with_suffix('.json').read_text())
model = load_pickle(lgbm_pkl)

preds = store.fetch_df('''
    SELECT user_id, risk_score, risk_level, rule_hits, model_probability, anomaly_score, snapshot_date
    FROM ops.model_predictions
    WHERE risk_level IN ('high', 'critical')
    ORDER BY risk_score DESC LIMIT 5
''')
# ...see examples/case_report_usr_*.json for output format
print(preds[['user_id', 'risk_score', 'risk_level']].to_string())
"

# Or via Makefile:
make cases
```

Output: `examples/case_report_usr_XXXXXX.json` — each report includes SHAP factors, rule hits, graph evidence, and narrative.

## Feature Drift Detection

```bash
cd bitoguard_core && . .venv/bin/activate
PYTHONPATH=. python services/drift.py

# Or via Makefile:
make drift
```

Output: JSON report comparing the two most recent feature snapshots. Flags features with >15% zero-rate change, >50% mean shift, or >50% std shift.

## API Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | /healthz | Health check |
| POST | /pipeline/sync | Trigger data sync |
| POST | /features/rebuild | Rebuild all features |
| POST | /model/train | Train + validate models |
| POST | /model/score | Score latest snapshot |
| GET | /alerts | List alerts (paginated) |
| GET | /alerts/{alert_id}/report | Full risk diagnosis report |
| POST | /alerts/{alert_id}/decision | Apply analyst decision |
| GET | /users/{user_id}/360 | 360-degree user view |
| GET | /users/{user_id}/graph | Entity graph for user |
| GET | /metrics/model | Latest validation metrics |
| GET | /metrics/threshold | Threshold sensitivity table |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| BITOGUARD_DB_PATH | `bitoguard_core/artifacts/bitoguard.duckdb` | DuckDB file path |
| BITOGUARD_ARTIFACT_DIR | `bitoguard_core/artifacts/` | Model and report artifacts |
| BITOGUARD_SOURCE_URL | `https://aws-event-api.bitopro.com` | Data source URL |
| BITOGUARD_ORACLE_DIR | `../bitoguard_sim_output` | Local CSV oracle fallback |
| BITOGUARD_LABEL_SOURCE | `hidden_suspicious_label` | Label column name |
| BITOGUARD_INTERNAL_API_PORT | `8001` | Backend API port |

## Offline / Demo Mode

Use the mock API as a local source:

```bash
# Terminal 1: start mock API
cd bitoguard_mock_api && . .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2: sync from mock source
cd bitoguard_core && . .venv/bin/activate
BITOGUARD_SOURCE_URL=http://localhost:8000 PYTHONPATH=. python pipeline/sync.py --full
```

## Troubleshooting

### DuckDB file locked
DuckDB only allows one writer at a time. If you get "connection refused" or lock errors, ensure no other process has the database open.

### Sync stuck or very slow
For the full live dataset (~600k+ rows), initial feature builds can take 10-15 minutes. Use `pipeline/refresh_live.py` for incremental updates after the first full run.

### Model artifact version mismatch warnings
If `sklearn` versions differ between training and inference environments, you may see `InconsistentVersionWarning`. Retrain the models in the same environment to resolve.

### Empty feature tables after sync
If `features.feature_snapshots_user_30d` is empty after sync, run:
```bash
PYTHONPATH=. python features/graph_features.py
PYTHONPATH=. python features/build_features.py
```
