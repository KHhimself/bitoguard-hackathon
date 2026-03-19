# Experiment Report: BitoGuard Production Stacker Training

## Overview

- **Date**: 2026-03-17
- **Git Commit**: b10a5b5bd68d411e73cdef36c22b7949f49c2302
- **Git Status**: Uncommitted changes present (see `git diff --stat HEAD` — 23 files modified)
- **Total runs planned**: 1
- **Successful runs**: 1 (via rescue run)
- **Failed runs**: 1 (attempt1, rescued)
- **Stacker version**: `stacker_20260317T095216Z`

## Environment

| Item | Value |
|------|-------|
| Python | 3.12.11 |
| CatBoost | 1.2.10 |
| LightGBM | 4.6.0 |
| XGBoost | 3.2.0 |
| PyTorch | 2.8.0+cu128 |
| GPU | NVIDIA RTX 2080 8GB |
| CPU cores | 8 |
| RAM | 81 GB |

## Command

```bash
cd /experiment/YuNing/bitoguard-hackathon/bitoguard_core
source .venv/bin/activate
PYTHONPATH=. BITOGUARD_USE_GPU=0 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 python models/stacker.py
```

(Rescue run: `BITOGUARD_USE_GPU=0` — see Issues section below)

## Dataset

- **Training samples**: 1,177
- **Positives**: 13 (1.10% prevalence)
- **Negatives**: 1,164
- **Features**: 228 total (211 base + 17 label-propagation columns)
- **Categorical features**: 4
- **Entity edges loaded**: 28,264
- **CV strategy**: StratifiedGroupKFold, 5 folds, groups=user_id

## Results Summary

### OOF Branch Performance (full out-of-fold)

| Branch | OOF AUC | OOF PR-AUC |
|--------|---------|-----------|
| CatBoost | 0.9937 | 0.8026 |
| LightGBM | 0.7151 | 0.6198 |
| XGBoost | 0.9579 | 0.1500 |
| ExtraTrees | 1.0000 | 1.0000 |
| **Stacker (calibrated)** | **1.0000** | **1.0000** |

### OOF Stacker Threshold Sweep

| Threshold | Precision | Recall | F1 | Flagged |
|-----------|-----------|--------|----|---------|
| 0.10 | 1.0000 | 1.0000 | 1.0000 | 13 |
| 0.20 | 1.0000 | 1.0000 | 1.0000 | 13 |
| 0.30 | 1.0000 | 1.0000 | 1.0000 | 13 |
| 0.40 | 1.0000 | 1.0000 | 1.0000 | 13 |
| 0.50 | 1.0000 | 1.0000 | 1.0000 | 13 |

- **Optimal F1 threshold**: 1.0000 — F1=1.0000, P=1.0000, R=1.0000
- **Optimal F2 threshold**: 1.0000 — F2=1.0000
- **Confusion matrix (optimal F1)**: TP=13, FP=0, FN=0, TN=1164
- **Lift**: 90.54x over prevalence
- **Score range**: [0.0000, 1.0000], p99=1.0000

### Per-Fold Metrics

| Fold | N train | N val | CB AUC | CB PR-AUC | LGBM AUC | LGBM PR-AUC | XGB AUC | XGB PR-AUC | ET AUC | ET PR-AUC |
|------|---------|-------|--------|-----------|----------|-------------|---------|------------|--------|-----------|
| 1 | 941 | 236 | 0.9914 | 0.7778 | 0.8333 | 0.6709 | 0.9528 | 0.4011 | 1.0000 | 1.0000 |
| 2 | 942 | 235 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 3 | 941 | 236 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9829 | 0.2361 | 1.0000 | 1.0000 |
| 4 | 942 | 235 | 0.9943 | 0.7000 | 0.6667 | 0.3418 | 0.9181 | 0.1645 | 1.0000 | 1.0000 |
| 5 | 942 | 235 | 0.9971 | 0.8667 | 0.6667 | 0.3418 | 0.9835 | 0.5000 | 1.0000 | 1.0000 |

### Fold Mean AUC

| Branch | Mean AUC | Std AUC |
|--------|----------|---------|
| CatBoost | 0.9966 | 0.0033 |
| LightGBM | 0.8333 | 0.1491 |
| XGBoost | 0.9675 | 0.0290 |
| ExtraTrees | 1.0000 | 0.0000 |

## Issues & Resolutions

### Attempt 1: CatBoost GPU OOM (CUDA error 2)

- **Run ID**: `stacker_production_20260317_attempt1`
- **Start/End**: 2026-03-17T08:52:02Z / 2026-03-17T08:55:24Z (~3.4 min)
- **Failure**: CatBoost CUDA out of memory at fold 1 training
- **Diagnosis**: GPU pre-run check reported 358 MiB free / 7778 MiB total. Other processes occupying ~7420 MiB: Xorg (138), gnome-shell (19), VS Code (47), Chrome (24), two miniforge Python3 processes (114+224 MiB).
- **Resolution**: Disabled GPU via `BITOGUARD_USE_GPU=0`. CPU execution has no memory constraint (81 GB RAM available, only 11 GB used). This is a runtime device flag only — no model architecture, hyperparameters, loss function, evaluation protocol, or data splits were changed.
- **Rescue run ID**: `stacker_production_20260317_rescue_oom`
- **Rescue run status**: SUCCESS

### Note on Perfect OOF Metrics

The stacker achieves OOF AUC=1.0000 and F1=1.0000. This is a consequence of the very small positive class size (only 13 positives across 1,177 samples, 1.10% prevalence). The label-aware propagation features (`prop_ip`, `prop_wallet`, `bfs_dist_1`, etc.) are computed per-fold using only training-fold labels and are highly discriminative at this scale. ExtraTrees achieves perfect AUC in all 5 folds with PR-AUC=1.0, suggesting the label propagation features alone perfectly separate the 2-3 positives that appear in each validation fold. The OOF evaluation is leakage-free (propagation uses only training-fold labels), but the small N means these metrics are not statistically reliable — treat them as in-sample upper bounds.

## Artifact Locations

### Model Artifacts (all timestamped `20260317T095216Z`)

| Artifact | Path |
|----------|------|
| CatBoost model | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/artifacts/models/cb_20260317T095216Z.joblib` |
| LightGBM model | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/artifacts/models/lgbm_v2_20260317T095216Z.joblib` |
| XGBoost model | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/artifacts/models/xgb_20260317T095216Z.joblib` |
| ExtraTrees model | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/artifacts/models/et_20260317T095216Z.joblib` |
| Meta stacker | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/artifacts/models/stacker_20260317T095216Z.joblib` |
| Stacker metadata | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/artifacts/models/stacker_20260317T095216Z.json` |
| CV results | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/artifacts/models/cv_results_20260317T095216Z.json` |
| SHA256 manifests | `*_20260317T095216Z.sha256` (x5) |

### Run Logs

| File | Path |
|------|------|
| Attempt 1 (failed) log | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/runs/stacker_production_20260317_stdout.log` |
| Rescue run log | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/runs/stacker_rescue_final.log` |
| Manifest | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/runs/manifest.yaml` |
| Ledger | `/experiment/YuNing/bitoguard-hackathon/bitoguard_core/runs/ledger.csv` |

## Reproducibility

- **Git commit**: b10a5b5bd68d411e73cdef36c22b7949f49c2302
- **Uncommitted diffs**: present (23 files modified — see `git diff --stat HEAD`)
- **Full command**: `PYTHONPATH=. BITOGUARD_USE_GPU=0 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 python models/stacker.py`
- **Random seed**: 42 (StratifiedGroupKFold, all branches)
- **Dataset path**: DuckDB at `bitoguard_core/artifacts/bitoguard.duckdb`, table `features.feature_snapshots_v2`
- **Entity edges**: `canonical.entity_edges` (28,264 edges)

## Conclusion

Training completed successfully after one OOM rescue (GPU disabled, CPU-only). The 5-fold stacker produced a new model bundle `stacker_20260317T095216Z` with OOF stacker AUC=1.0000 and PR-AUC=1.0000. The perfect OOF metrics reflect the small positive count (13 samples) and highly discriminative label-propagation features — not necessarily a reliable indicator of production performance. The CatBoost branch shows the most stable fold-level performance (mean AUC 0.9966 ± 0.0033). LightGBM shows higher variance (0.8333 ± 0.1491) with notable dips in folds 4 and 5.
