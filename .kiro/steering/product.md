---
inclusion: always
---

# BitoGuard Product Domain

BitoGuard is an AML/fraud detection system for cryptocurrency exchanges generating risk scores (0-1000+) and alerts with SHAP explanations for compliance review.

## Core Entities

- **User**: Exchange account with verification tier, profile, transaction history
- **Risk Score**: Composite from 6 modules (rules, statistical, ML, anomaly, graph, ops)
- **Alert**: High-risk notification with SHAP explanations and top contributing factors
- **Feature**: ~155 engineered signals capturing behavior patterns, peer deviation, graph relationships
- **Transaction**: Fiat deposit/withdrawal, crypto transfer, trade order

## Data Flow

```
BitoPro API → Sync → DuckDB → Features → Train → Score → Alerts
```

## 6-Module Architecture

Always identify which module your change affects:

**M1: Rules** (`models/rule_engine.py`)
- 11 deterministic AML rules with severity weights
- Examples: blacklist proximity, large cash-outs, dormancy reactivation, structuring
- Modify for: new compliance rules, threshold adjustments

**M2: Statistical** (`features/build_features_v2.py`, `features/*_features.py`)
- Peer-deviation features, cohort percentile ranks, rolling windows, z-scores
- ~155 features across crypto, trading, profile, IP, sequence, swap domains
- Modify for: new behavioral signals, cohort comparisons

**M3: Supervised ML** (`models/train.py`, `models/train_catboost.py`, `ml_pipeline/`)
- LightGBM/CatBoost with temporal splits, precision@K optimization
- AWS SageMaker: training, tuning, model registry
- Modify for: model architecture, hyperparameters, training pipeline

**M4: Anomaly Detection** (`models/anomaly.py`)
- IsolationForest for novelty detection
- Modify for: anomaly thresholds, feature selection

**M5: Graph Analysis** (`features/graph_*.py`)
- NetworkX heterogeneous graphs: user-IP-wallet relationships
- Risk propagation, blacklist proximity, community detection
- Modify for: graph construction, propagation algorithms

**M6: Operations** (`services/explain.py`, `services/drift.py`, `pipeline/refresh_live.py`)
- SHAP explanations, drift detection, incremental refresh
- Modify for: explanation logic, monitoring, production pipelines

## MANDATORY Product Constraints

### Temporal Correctness
- NEVER use future data in past predictions (data leakage is a critical bug)
- Features MUST use point-in-time data only
- Training MUST use temporal splits: train on past, validate on future
- Watermark-based incremental refresh preserves temporal ordering
- When adding features: verify no forward-looking calculations

### Explainability
- Every alert MUST include SHAP explanations
- Feature names MUST be human-readable for compliance officers
- Explanations MUST show top 5-10 contributing factors
- When adding features: provide clear descriptions in `features/registry.py`

### Performance SLAs
- Full sync: <10 minutes (~100K+ transactions)
- Feature building: <10 minutes (full snapshot)
- API response: <2 seconds (user 360 view)
- Incremental refresh: every 15 minutes (production)
- When optimizing: profile first, maintain SLAs

### Compliance Standards
- System detects 11 AML rule violations
- Optimize for precision@K, NOT raw accuracy (compliance reviews top K alerts)
- Maintain audit trail for all alerts and decisions
- When adding rules: document regulatory basis and severity rationale

## Domain Terminology

Use consistently in code, docs, UI:

- **Peer deviation**: User behavior difference from cohort (age group, verification tier)
- **Dormancy**: Inactive period followed by sudden activity (reactivation risk)
- **Structuring**: Breaking large transactions to evade detection
- **Blacklist proximity**: Graph distance to known bad actors (shared IP/wallet)
- **Risk propagation**: Risk scores flowing through graph edges
- **Watermark**: Timestamp checkpoint for incremental data refresh
- **Precision@K**: Model accuracy in top K highest-risk predictions
- **Temporal split**: Train/validation split preserving time ordering
- **Point-in-time features**: Features using only data available at prediction time

## Module Placement

**New AML rule** → `models/rule_engine.py` (RULES dict + severity weight)
**New feature domain** → `features/<domain>_features.py` + register in `features/registry.py`
**New ML algorithm** → `models/train_<algorithm>.py` (local) or `ml_pipeline/` (SageMaker)
**New pipeline step** → `pipeline/<step_name>.py`
**New API endpoint** → `api/main.py` (FastAPI route)
**New service logic** → `services/<service_name>.py`
**New graph algorithm** → `features/graph_<algorithm>.py`
**New Lambda** → `infra/aws/lambda/<function_name>/lambda_function.py`
**New Terraform** → `infra/aws/terraform/<resource_type>.tf`

## Product Principles (Priority Order)

1. **Explainability First**: Can compliance officers understand this? If not, redesign.
2. **Temporal Correctness**: Does this use future data? If yes, it's a bug.
3. **Incremental by Default**: Can this run incrementally with watermarks? If not, justify.
4. **Modular Architecture**: Can this be tested/deployed independently? If not, refactor.
5. **Compliance-Driven Metrics**: Optimize precision@K, not raw accuracy.

## Implementation Patterns

### Adding a Feature
1. Create `features/<domain>_features.py` with builder function
2. Register in `features/registry.py` with human-readable description
3. Add pytest in `tests/test_<domain>_features.py`
4. Verify temporal correctness (no future data leakage)
5. Retrain models, check precision@K impact

### Adding an AML Rule
1. Add to `models/rule_engine.py` RULES dict with severity weight
2. Document regulatory basis in docstring
3. Add test cases with known violations
4. Update alert explanations

### Modifying ML Pipeline
1. Local: update `models/train.py` or `features/build_features_v2.py`
2. AWS: update `ml_pipeline/` entrypoints and `infra/aws/terraform/`
3. Test locally first, deploy to dev, monitor drift/performance

### Investigating Alerts
1. Check SHAP explanations in alert JSON
2. Query user history: `artifacts/bitoguard.duckdb`
3. Visualize graph if graph features are top contributors
4. Compare to peer cohort for context
