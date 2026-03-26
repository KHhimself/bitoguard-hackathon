# BitoGuard Production Configuration

## Model Architecture

The production model is a stacked ensemble combining multiple base models:

- Base A: CatBoost (multi-seed, 4 seeds)
- Base B: CatBoost transductive (with graph features)
- Base C: GraphSAGE GNN (DISABLED - replaced by dummy zeros, confirmed zero blend weight)
- Base C&S: Correct-and-Smooth graph post-processing (ACTIVE)
- Base D: LightGBM (multi-seed, 3 seeds)
- Base E: XGBoost (multi-seed, 2 seeds)

Note: 4 active branches (Base A, B, C&S, D, E). GraphSAGE GNN exists in architecture but is disabled.

## Validation Protocol

### Primary Validation
- Protocol: StratifiedKFold (5 folds, user-level)
- Mode: Transductive label masking
- Purpose: Development metrics

### Secondary Validation (Group-Stress)
- Protocol: StratifiedGroupKFold (5 folds, group-level)
- Groups: Strong groups via IP/wallet/relation edges
- Purpose: Group-aware practical estimate
- Note: Blend weights are re-tuned on secondary OOF via tune_blend_weights(), introducing some in-sample bias

### Honest Validation (NEW)
- Protocol: Inner-fold selection
- All selection steps (blend weights, calibration, threshold) performed inside each fold's training portion
- Purpose: Unbiased out-of-sample estimate
- Eliminates in-sample selection bias from reported metrics

## Performance Metrics

Validation results will be updated after running the honest evaluation pipeline.

## Configuration

- Random seed: 42
- CV folds: 5
- Calibration: Isotonic (selected via cross-validation)
- Threshold: F1-optimized with bootstrap validation
