# BitoGuard Core

`bitoguard_core` is the AML risk detection engine for BitoPro cryptocurrency exchange.

## Production Pipeline (E15)

Trained on 707K raw events from 63,770 users (51,017 labeled, 12,753 unlabeled).

### Features (201 total)
- **158 base features** (`official/features.py`): TWD/crypto/trade/swap aggregates, FATF typology patterns, graph structure, anomaly scores, rule triggers
- **20 sequence features** (`official/sequence_features.py`): inter-deposit timing, burst detection, chain patterns, IP entropy, wallet behavior
- **23 temporal features** (`official/temporal_features.py`): windowed acceleration, cycle efficiency, periodicity detection

### Model Architecture
- **Base A**: CatBoost x4 seeds [42,52,62,72], depth=7, iterations=1500, focal_gamma=2.0
- **Base B**: CatBoost transductive (label-aware graph features, CPU, l2_leaf_reg=5.0)
- **Base C**: GraphSAGE — disabled (confirmed zero blend weight across all experiments)
- **Base D**: LightGBM x3 seeds [42,123,456]
- **Base E**: XGBoost x2 seeds [42,123], HPO-tuned (depth=6, lr=0.058)
- **C&S**: Correct-and-Smooth graph post-processing on Base A (alpha=0.5, 50 iterations)
- **Stacker**: BlendEnsemble (cs_x_anomaly=65%, base_e=30%, C&S=5%)

### Results
- **Primary F1**: 0.4418 (5-fold transductive CV)
- **Secondary F1**: 0.4314 (StratifiedGroupKFold, unbiased estimate)
- **Threshold**: 0.21

See `docs/PRODUCTION_CONFIG.md` and `docs/METHODS_AND_RESULTS.md` for full details.

## Setup

```bash
cd bitoguard_core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Retrain

```bash
cd bitoguard_core
PYTHONPATH=. python -m official.pipeline
```

Data path defaults to `../data/aws_event/clean/` (configurable via `BITOGUARD_AWS_EVENT_CLEAN_DIR`).

## Tests

```bash
PYTHONPATH=. pytest tests/ -v
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
| Official bundle | `artifacts/official_bundle.json` |
| CatBoost models | `artifacts/models/official_catboost_base_a_*.pkl` |
| XGBoost models | `artifacts/models/official_xgboost_base_e_*.pkl` |
| LightGBM models | `artifacts/models/official_lgbm_base_d_*.pkl` |
| Stacker | `artifacts/models/official_stacker_*.pkl` |
| Validation report | `artifacts/reports/official_validation_report.json` |
| Predictions | `artifacts/predictions/official_predict_scores.csv` |
| Archived experiments | `official/_archive/` |
