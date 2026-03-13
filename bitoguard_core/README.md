# BitoGuard Core

`bitoguard_core` is the AML risk detection engine. It handles:

- Source ingestion from BitoPro AWS Event API into DuckDB
- Canonical event schema: users, login_events, fiat_transactions, crypto_transactions, trade_orders
- Graph feature extraction (shared IP/wallet/blacklist proximity) via NetworkX
- Feature snapshot building with peer-deviation metrics and rolling windows
- LightGBM supervised classifier (leakage-safe temporal splits) + IsolationForest anomaly model
- Risk scoring, alert generation, SHAP case diagnosis
- Incremental refresh with watermark checkpointing
- Feature drift detection
- FastAPI serving 13 endpoints for the Next.js frontend

## Setup

```bash
cd bitoguard_core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Override default source:

```bash
export BITOGUARD_SOURCE_URL=https://aws-event-api.bitopro.com
```

## Using the Makefile (recommended)

```bash
make test        # 61 tests
make sync        # Full data sync from BitoPro
make features    # Build graph + statistical features
make train       # Train LightGBM + IsolationForest
make evaluate    # Holdout evaluation (P@K, calibration, FI top-20)
make ablation    # Module ablation study
make refresh     # Incremental watermark refresh
make score       # Score users → alerts
make drift       # Feature drift health check
make cases       # Generate SHAP case reports (examples/)
make serve       # Start API on port 8001
```

## Manual pipeline steps

```bash
source .venv/bin/activate

PYTHONPATH=. python pipeline/sync.py --full
PYTHONPATH=. python features/graph_features.py
PYTHONPATH=. python features/build_features.py
PYTHONPATH=. python models/train.py
PYTHONPATH=. python models/anomaly.py
PYTHONPATH=. python models/score.py
PYTHONPATH=. python models/validate.py
PYTHONPATH=. python services/drift.py
PYTHONPATH=. python scripts/ablation_study.py
```

## Tests

```bash
PYTHONPATH=. pytest tests/ -v
# 61 passed: test_model_pipeline, test_rule_engine, test_source_integration, test_smoke
```

## API

```bash
PYTHONPATH=. uvicorn api.main:app --reload --port 8001
```

Key endpoints: `/alerts`, `/alerts/{id}/report`, `/users/{id}/graph`, `/metrics/model`, `/metrics/drift`

See full endpoint list in the root `README.md`.

## Key Artifacts

| Artifact | Location |
|----------|----------|
| DuckDB database | `artifacts/bitoguard.duckdb` |
| LightGBM model | `artifacts/models/lgbm_*.pkl` |
| IsolationForest | `artifacts/models/iforest_*.pkl` |
| Validation report | `artifacts/validation_report.json` |
| Ablation report | `artifacts/ablation_report.json` |
| Case reports | `../examples/case_report_*.json` |
