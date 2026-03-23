# Archived Experiment Code

These modules were developed and tested during the experiment phase
but are NOT part of the production pipeline.

## Why archived (not deleted)
- Preserves research history and negative results
- Some modules may be useful for future research
- Experiment logs document what was tried and why it failed

## Experiment results summary
| Module | Experiment | Result | Why archived |
|--------|-----------|--------|-------------|
| configurable_pipeline.py | Framework | Had 3 poison bugs | Abandoned |
| community_features.py | E19-style | Label leakage | Disabled |
| self_training.py | E13 | No primary gain, secondary -0.022 | No effect |
| hpo.py | Phase 3 | Poisoned configurable_pipeline | Stale params |
| hpo_edge_weights.py | E-series | No improvement | Stale |
| hpo_threshold.py | E-series | No improvement | Stale |
| nnpu_loss.py | E-series | PU learning experiment | No gain |
| lag_features.py | E-series | Temporal lag features | No gain |
| dgi_embeddings.py | E-series | Deep Graph Infomax | Label leakage |
| sequence_model.py | E-series | Pseudo-sequence model | Unused |
| gru_model.py | E16 | AP=0.21, zero blend weight | Too weak |
| event_sequence.py | E16 | Event sequence features | Zero weight |
| tx_features.py | E20 | Transaction-level features | AP=0.20, zero weight |
| tx_model.py | E20 | Transaction-level LightGBM | Zero weight |
| onboarding_features.py | E19 | AP+0.02 but F1-0.009 | AP/F1 disconnect |
| ablation_runner.py | Framework | Ablation experiment runner | Framework only |
| experiment_tracker.py | Framework | Experiment tracking | Framework only |
| demo_pack.py | Demo | Demo packaging script | Not pipeline |
| generate_submission.py | Submission | Competition submission | Not pipeline |
| hpo_xgboost.py | HPO | XGBoost hyperparameter search | Results applied |
| hpo_catboost.py | HPO | CatBoost hyperparameter search | Results applied |
| OFFICIAL_EXPERIMENT_SUMMARY_20260317.md | Baseline results | F1=0.363 | Superseded by E15 (F1=0.4418) |
| OFFICIAL_EXPERIMENT_SUMMARY_20260319.md | v46 results | F1=0.368 | Superseded by E15 (F1=0.4418) |
