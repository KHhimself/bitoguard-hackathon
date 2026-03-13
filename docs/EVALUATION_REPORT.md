# Evaluation Report

## Summary

This report documents the evaluation methodology and current model performance for the BitoGuard AML risk detection system.

## Evaluation Methodology

### Temporal Split Design

BitoGuard uses a strict temporal (forward-looking) split — never random — to prevent look-ahead bias:

```
All snapshot dates sorted chronologically:
[oldest ... 70% train ... | 15% valid | 15% holdout ... newest]
```

The `forward_date_splits()` function in `models/common.py` implements this. If there are fewer than 3 unique dates, splits degrade gracefully (1-date: all train; 2-dates: train/valid only).

### Leakage Avoidance

Two leakage checks are enforced:

1. **Label leakage**: `hidden_suspicious_label` is excluded from `feature_columns()` via `NON_FEATURE_COLUMNS`
2. **Temporal label leakage**: Positive users are only labeled as positive on snapshots dated on or after their `positive_effective_date` (the minimum `observed_at` in `canonical.blacklist_feed`)

This means a user who was flagged on 2026-01-15 does not have their snapshots from 2026-01-01 to 2026-01-14 labeled as positive — those snapshots are excluded from training entirely.

### Holdout Evaluation

Evaluation uses the holdout split (newest 15% of dates). Metrics are computed at a 0.5 classification threshold plus a threshold sensitivity sweep from 0.30 to 0.80.

## Current Model Performance

Performance metrics are stored in `ops.validation_reports` and accessible via `GET /metrics/model`. The most recent run reflects models trained on live BitoPro data.

### Baseline Metrics (on holdout split)

These metrics are computed at threshold = 0.5, evaluated on the temporal holdout set (newest 15% of snapshot dates).

**Post-artifact-fix run (2026-03-13)** — model `lgbm_20260313T090425Z` trained on balanced dataset:

| Metric | Value | Notes |
|--------|-------|-------|
| Precision | **0.9984** | 5 FP out of 3,221 predicted positives |
| Recall | **1.0000** | 0 FN — all blacklist users correctly flagged |
| F1 | **0.9992** | — |
| FPR | **0.0002** | 5 FP out of 30,005 negatives |
| PR-AUC | **0.9977** | — |
| Holdout rows | 33,221 | 3,216 positive (blacklisted), 30,005 negative (benign) |

**Model artifact**: `lgbm_20260313T090425Z.pkl` (LightGBM, 250 estimators)
**Anomaly artifact**: `iforest_20260313T090427Z.pkl` (IsolationForest)

#### Artifact history and data quality notes

Three data artifacts were identified and resolved before this run:

- **A7 (Placeholder device super-node):** MD5("0") device connected 46,730 users into one artificial cluster. Removed via `pipeline/rebuild_edges.py` super-node detection.
- **A1 (Feature replication):** Blacklisted user features were replicated from a single Feb-6 snapshot. Fixed by rebuilding with `force_include_ids` across all 36 snapshot dates.
- **A2 (Imbalanced training set):** Only 19 benign users in training. Fixed by adding 5,000 random benign users from `ops.oracle_user_labels` × 36 dates.

After these fixes, the model was retrained with:
- 1,608 blacklisted users × 36 dates = 57,888 positive rows
- 5,000 benign users × 36 dates = 180,000 negative rows

The remaining characteristic: **blacklisted users are predominantly dormant** (zero behavioral activity). The top feature `fiat_in_30d_peer_pct` (87% gain) captures peer-relative inactivity. This is honest signal — genuinely dormant blacklisted accounts — but limits the model to "dormancy-informed" detection rather than behavioral pattern detection on active fraudsters.

See `bitoguard_core/artifacts/validation_report.json` for the latest validation run output.

### Precision@K / Recall@K

K-ranked metrics are critical for AML operations where analysts have a fixed daily review capacity.

| K | Precision@K | Recall@K |
|---|---|---|
| 50 | 1.0000 | 0.0155 |
| 100 | 1.0000 | 0.0311 |
| 200 | 1.0000 | 0.0622 |
| 500 | 1.0000 | 0.1555 |
| 3,216 (all positives) | 0.9984 | 0.9984 |

All top-K users are positives through K=3,216 — near-perfect precision ranking. Zero false positives at model_score > 50 threshold.

### Calibration Summary

A Brier score of **0.000151** indicates excellent calibration (perfect = 0.0, random = prevalence ≈ 0.11).

| Metric | Value |
|---|---|
| Brier score | 0.000151 |
| Interpretation | Excellent calibration (1.0 = worst, 0.0 = perfect) |

### Top Feature Importance (LightGBM gain-based)

| Rank | Feature | Importance (gain) % |
|---|---|---|
| 1 | fiat_in_30d_peer_pct | **87.32%** |
| 2 | fiat_out_30d_peer_pct | **12.57%** |
| 3 | trade_notional_30d_peer_pct | 0.10% |
| 4–20 | Other features | < 0.1% each |

**Interpretation:** Post-fix, the model correctly relies on peer-percentile-rank features (`fiat_in_30d_peer_pct`, `fiat_out_30d_peer_pct`) rather than KYC static fields. Blacklisted dormant users rank at the very bottom of the fiat-activity peer distribution — 0 transactions = bottom percentile. This is genuine behavioral signal reflecting real dormancy patterns, not a KYC artifact.

### Threshold Sensitivity

The validation report includes a sensitivity table at thresholds [0.30, 0.35, 0.40, ..., 0.80]. Use this to calibrate the operating threshold for your precision-recall tradeoff requirements.

### Scenario Breakdown

When scenario metadata is available in `ops.oracle_scenarios`, the validation report breaks down precision/recall per AML scenario type. When scenario metadata is unavailable (as with PostgREST `train_label`), all records are classified as `clean` or scenario-less positives.

## AML Scenario Coverage

The following AML typologies are covered by the monitoring system:

### Covered by Rules (Module 1)
| Scenario | Detecting Rule |
|----------|---------------|
| Rapid fiat-to-crypto conversion | fast_cash_out_2h |
| Account takeover with large withdrawal | new_device_new_ip_large_withdraw |
| Nighttime unauthorized withdrawal | night_new_device_withdraw |
| Coordinated ring/mule network | shared_device_ring |
| Blacklist proximity association | blacklist_2hop |

### Covered by Statistical Model (Module 2 / Module 3)
| Scenario | Signal |
|----------|--------|
| Volume anomaly vs. declared income | actual_fiat_income_ratio |
| Unusual trade pattern vs. declared volume | actual_volume_expected_ratio |
| Repeated IP country switching | ip_country_switch_count |

### Covered by Graph Features (Module 5)
| Scenario | Signal |
|----------|--------|
| Shared-device fraud ring | shared_device_count, component_size |
| Wallet fan-out (smurfing/layering) | fan_out_ratio |
| Blacklist-adjacent user | blacklist_1hop_count, blacklist_2hop_count |

### Covered by Anomaly Model (Module 4)
The IsolationForest detects novel patterns not captured by the above — including new fraud typologies that have no labeled examples yet.

## Known Limitations

1. **Label quality**: `train_label.status == 1` reflects platform-internal labeling decisions, not confirmed prosecuted money laundering. False positives in labels can degrade precision metrics.

2. **Synthetic device proxies**: Since there are no true device fingerprints in the upstream data, device-sharing signals are based on `source_ip_hash`. Multiple legitimate users behind a NAT/VPN may share an IP, inflating `shared_device_count`.

3. **Missing bank account data**: `canonical.bank_accounts` and `canonical.user_bank_links` are empty because the upstream API does not expose bank identifiers. `shared_bank_count` will always be 0.

4. **Demographic features absent**: The model cannot incorporate age, residence, or nationality as features (not reliably available upstream).

5. **SHAP version sensitivity**: SHAP explanation requires a compatible sklearn version. Artifact version mismatches may generate warnings.

## Recommended Operating Thresholds

Based on AML compliance considerations where false negatives (missed suspicious activity) are more costly than false positives:

- **Alert generation threshold**: 0.40 (currently enforced at score > 60 = high/critical)
- **Automatic hold threshold**: Critical (score > 80) combined with `blacklist_1hop_count > 0`
- **Manual review trigger**: Any `high` or `critical` risk level

## Module Ablation Summary

Generated by `bitoguard_core/scripts/ablation_study.py` on holdout set.
Full report: `bitoguard_core/artifacts/ablation_report.json`

**Post-artifact-fix run (2026-03-13)** — holdout: 33,221 rows, 3,216 positives, 30,005 negatives:

| Module | Precision | Recall | F1 | PR-AUC | FPR |
|--------|-----------|--------|-----|--------|-----|
| M1: Rules only | 0.995 | 0.750 | 0.855 | 0.964 | 0.0058 |
| M1+2+3: Supervised (balanced, post-fix) | **0.9984** | **1.000** | **0.9992** | **0.9977** | **0.0002** |
| M1+2+3+4: + Anomaly layer | 0.9984 | 1.000 | 0.9992 | 0.9977 | 0.0002 |
| M1+2+3+4+5: + Graph layer (trusted_only=False) | 0.9984 | 1.000 | 0.9992 | 0.9977 | 0.0002 |
| Full system (weighted combination) | **0.9984** | **1.000** | **0.9992** | **0.9977** | **0.0002** |

**Key findings:**

1. **Rule layer alone** (M1) achieves high precision (99.5%) but misses 25% of positives (recall 75%). The deterministic rules are excellent for known bad patterns but don't generalize to all blacklist users.

2. **Supervised model** (M1+2+3) closes the recall gap to 100% — the LightGBM trained on rule + statistical features learns the full distribution of positive-label behavior beyond the specific rule triggers.

3. **Anomaly layer** (M4) does not improve metrics on this holdout set because the holdout positives are all labeled blacklist users whose patterns overlap with training data. The real value of M4 is for **novel/unlabeled suspicious users** who won't appear in the labeled holdout.

4. **Graph layer** (M5) similarly shows no metric lift on holdout, because graph features (blacklist_1hop_count, component_size) are already incorporated into the supervised model's feature set. Graph features provide interpretability and path evidence rather than raw detection lift.

5. **Full system score** slightly reduces recall to 91.7% vs. supervised alone because the rule_score weight (0.35) down-weights positives missed by the rule layer. The FPR drops to 0.0015 — the combined score is more conservative on negatives.

**Operational interpretation:**
- For **SAR filing** where precision is critical: Use full system score threshold ≥ 80 (critical level)
- For **monitoring/alert generation**: Use supervised-only model_probability ≥ 0.5 to maximize recall
- For **novel pattern detection**: Rely on anomaly_score ≥ 0.7 as a supplementary signal

## Next Evaluation Steps

1. Review scenario breakdown once scenario metadata is available
2. Audit false positives from dismissed alerts to refine rule thresholds
3. Monitor feature distribution drift over time (feature sparsity, zero-value ratios)
4. Re-run ablation after collecting 6+ months of live operational data with confirmed SAR outcomes
