# Model Card

## Model Overview

BitoGuard uses the following models and heuristics:

| Component | Type | Valid? | Notes |
|-----------|------|--------|-------|
| **M0 Dormancy** | Deterministic heuristic | ✅ VALID | PR-AUC=0.9823 baseline every module must beat |
| **M1 Rule Engine** | Deterministic rules | ⚠ CAUTION | Cannot fire on dormant users (A3 artifact) |
| **M3 LightGBM** | Supervised classifier | ⚠ CAUTION | Near-perfect metrics reflect data artifacts, not fraud patterns |
| **M4 IsolationForest** | Unsupervised anomaly | ✅ VALID | Only module with verified artifact-free signal (PR-AUC=0.9724) |
| **M5 Graph Risk** | Deterministic formula | ⚠ GUARDED | Unsafe features disabled by default (`graph_trusted_only=True`) |

### Data Artifact Warning

The current dataset has three interacting artifacts (A1+A2+A3) that inflate all module metrics:
- **A1** (future backfill): All 1,608 blacklisted users' features were generated from a single Feb-6 snapshot
- **A2** (duplicate inflation): This produces identical feature vectors across all dates for positive users
- **A3** (inactivity shortcut): 100% of blacklisted users have zero behavioral activity — trivially detectable

**M0 Dormancy Baseline**: PR-AUC=0.9823, ROC-AUC=0.9882 — a trivial `sum(behavioral_features) == 0` rule. Any module claiming higher performance must prove it adds signal beyond dormancy detection.

See `docs/DORMANCY_BASELINE.md`, `docs/GRAPH_HONESTY_AUDIT.md`, `reports/M5_FINAL_VERDICT.md`.

---

---

## Module 3: LightGBM Supervised Risk Model

### Model Details

| Property | Value |
|----------|-------|
| Framework | LightGBM `LGBMClassifier` |
| Task | Binary classification (suspicious=1 vs benign=0) |
| Output | Probability score in [0, 1] |
| Artifact prefix | `lgbm_` |
| Artifact location | `bitoguard_core/artifacts/models/` |

### Hyperparameters

| Parameter | Value |
|-----------|-------|
| n_estimators | 250 |
| learning_rate | 0.05 |
| num_leaves | 31 |
| subsample | 0.9 |
| colsample_bytree | 0.9 |
| random_state | 42 |
| scale_pos_weight | negatives / positives (class-balanced) |

### Training Data

- Source: `features.feature_snapshots_user_30d` joined with `ops.oracle_user_labels`
- Label: `hidden_suspicious_label` from `ops.oracle_user_labels` (derived from `train_label.status == 1`)
- Leakage guard: positive labels are only included for snapshots on or after `positive_effective_date` (the minimum `observed_at` in `canonical.blacklist_feed` for that user)

### Temporal Split

Training uses a forward-looking temporal split (no random shuffling):

| Split | Fraction | Description |
|-------|----------|-------------|
| train | 70% of dates | Oldest data — used for fitting |
| valid | 15% of dates | Used for early stopping metric |
| holdout | 15% of dates | Final evaluation only |

The `forward_date_splits()` function guarantees no future data leaks into training.

### Feature Encoding

Categorical features are one-hot encoded via `pd.get_dummies`. Unknown categories at inference time are mapped to 0 via `reindex`. The `encoded_columns` list is persisted in the `.json` metadata file alongside the `.pkl` model.

### Intended Use

- Rank users by AML risk
- Contribute 45% weight to the composite `risk_score`
- Should be retrained periodically on fresh feature snapshots

### Limitations

- **Data artifact (A1+A2+A3)**: Near-perfect holdout metrics (P=0.9975, R=1.0) are driven by identical feature vectors across all training dates for blacklisted users — not genuine temporal fraud patterns. See `docs/DORMANCY_BASELINE.md`.
- Trained on labels derived from `train_label.status`, which may reflect platform-internal blacklist decisions rather than ground-truth confirmed laundering
- Categorical vocabulary (kyc_level, occupation, segment) is fitted at training time; new categories at inference receive a 0 encoding
- The model does not directly incorporate temporal trends across snapshots (each snapshot is treated independently)

---

## Module 4: IsolationForest Anomaly Model

### Model Details

| Property | Value |
|----------|-------|
| Framework | scikit-learn `IsolationForest` |
| Task | Unsupervised anomaly detection |
| Output | Anomaly score in [0, 1] (normalized from negative `score_samples`) |
| Artifact prefix | `iforest_` |
| Artifact location | `bitoguard_core/artifacts/models/` |

### Hyperparameters

| Parameter | Value |
|-----------|-------|
| n_estimators | 200 |
| contamination | max(0.01, mean(hidden_suspicious_label)) |
| random_state | 42 |

### Training Data

- Same feature set as LightGBM
- Trained only on the training split (no label required — unsupervised)
- The contamination parameter is initialized from the label prevalence in training data

### Intended Use

- Detect novel behavioral patterns not captured by the supervised model or rules
- Contribute 10% weight to the composite `risk_score`
- Particularly useful for detecting new fraud typologies that have not yet appeared in labeled data

### Anomaly Score Normalization

```python
anomaly_raw = -model.score_samples(x)  # Higher = more anomalous
anomaly_score = (anomaly_raw - anomaly_raw.min()) / (anomaly_raw.max() - anomaly_raw.min() + 1e-9)
```

Score is normalized per batch to [0, 1].

---

## Module 5: Graph Risk Score

> **⚠ GUARDED — Unsafe features disabled by default.**
> Set `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=false` only after executing `docs/GRAPH_RECOVERY_PLAN.md`.

This is not a trained model but a deterministic formula. In **trusted-only mode** (default), only `shared_bank_count` and `shared_wallet_count` are active; the unsafe features are zeroed:

```python
# Full formula (requires BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=false)
graph_risk = (
    blacklist_1hop_count * 0.6    # UNSAFE — quarantined (label leakage via proximity)
  + blacklist_2hop_count * 0.4    # UNSAFE — quarantined
  + shared_device_count * 0.05    # UNSAFE — quarantined (placeholder super-node A7)
  + shared_bank_count   * 0.05    # trusted ✓
).clip(lower=0) / max(1.0, batch_max)

# Default production formula (trusted_only=True):
# Only shared_bank_count contributes; all unsafe features are 0
```

**Why quarantined**: A graph audit (see `reports/M5_FINAL_VERDICT.md`) found that 46,730 users share a placeholder device node (`dev_cfcd208495d565ef66e7dff9f98764da` = MD5("0")), creating an artificial giant component that accounts for all apparent M5 signal.

Contributes 10% weight to the composite `risk_score`.

---

## Composite Risk Score

```
risk_score = (
    0.35 * rule_score
  + 0.45 * model_probability
  + 0.10 * anomaly_score
  + 0.10 * graph_risk
) * 100
```

---

## Evaluation Metrics

Metrics are computed on the holdout split after training and stored in `ops.validation_reports`.

| Metric | Description |
|--------|-------------|
| precision | TP / (TP + FP) at threshold 0.5 |
| recall | TP / (TP + FN) at threshold 0.5 |
| f1 | Harmonic mean of precision and recall |
| fpr | FP / (FP + TN) — false positive rate |
| average_precision | Area under precision-recall curve |
| threshold_sensitivity | Precision/recall/f1 at thresholds 0.30–0.80 |
| scenario_breakdown | Per-scenario precision/recall (when available) |

---

## Retraining Protocol

1. Ensure `canonical.*` tables are up to date via `pipeline/sync.py`
2. Rebuild features: `POST /features/rebuild`
3. Retrain: `POST /model/train` (trains both LightGBM and IsolationForest, then validates)
4. Inspect validation report via `GET /metrics/model`
5. If metrics are acceptable, the new artifacts replace the previous ones
6. The old `.pkl` and `.json` files remain in `artifacts/models/` for audit purposes (they are sorted by version timestamp)

---

## Fairness and Compliance Notes

- The model does not use demographic features (age, sex, nationality) as direct inputs
- `kyc_level`, `occupation`, and `declared_source_of_funds` are included as behavioral/profile features but not protected characteristics
- All predictions are explainable via SHAP values (`services/explain.py`)
- Every high-risk output includes a `rule_hits` list for analyst transparency
- The `recommended_action` field in the risk diagnosis is advisory only
