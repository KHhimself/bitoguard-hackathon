# Production Pipeline (E15)

## Final Results
- Primary F1: 0.4418
- Primary AP: 0.3842
- Secondary F1: 0.4304
- Threshold: 0.2071
- Date: 2026-03-22

## Evaluation Bias Note
Primary F1=0.4418 includes in-sample selection bias from:
- BlendEnsemble weight grid search on full OOF predictions (~+0.01)
- Isotonic calibration + threshold selection on same OOF data

**Secondary F1=0.4314 is the unbiased out-of-sample estimate.**
Secondary uses StratifiedGroupKFold (graph-aware group splits) with
the primary's calibrator and threshold applied without re-tuning.
Primary-Secondary gap of +0.0104 F1 is within normal range.

## Configuration
- Features: 158 base + 20 sequence + 23 temporal = 201 total
- GNN: OFF (zero contribution, permanently disabled)
- C&S: alpha=0.5/0.5, 50+50 iterations, on Base A

## Model Architecture
- Base A: CatBoost x4 seeds [42,52,62,72], depth=7, iterations=1500
- Base B: CatBoost transductive (1 seed, CPU, l2_leaf_reg=5.0)
- Base C: GraphSAGE (disabled, dummy zeros)
- Base D: LightGBM x3 seeds [42,123,456]
- Base E: XGBoost x2 seeds [42,123], depth=6, lr=0.058 (HPO optimized)
- C&S: Correct-and-Smooth on Base A
- Stacker: BlendEnsemble (cs_x_anomaly=65%, base_e=30%, C&S=5%)

## Reproduce
```bash
cd bitoguard_core
export BITOGUARD_AWS_EVENT_CLEAN_DIR=data/aws_event/clean
PYTHONPATH=. python -m official.pipeline
```

## Experiment History
See `official/_archive/` for all experiment code and logs.
Full experiment log: 20+ experiments, baseline 0.363 -> 0.4418 (+21.7%)
