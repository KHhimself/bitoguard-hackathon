# BitoGuard Evaluation Protocol

## Overview

This document defines the 6-layer honest evaluation protocol for the BitoGuard AML detection system.
All results must satisfy purity gates before being reported as valid. Any gate failure invalidates
the associated metric and must be disclosed.

---

## Part 1: Purity Gates (A–E)

### Gate A — Time Purity

**Definition:** Feature vectors for any given snapshot date must be computed exclusively from data
that was observable at that snapshot date. No future information may be incorporated.

**Violation indicators:**
- A1: Future snapshot backfill — blacklisted users have feature vectors on early training dates that
  are identical to a later (future) snapshot date, indicating the future snapshot was pasted backward.
- A6: Future graph leakage — graph topology (component membership, hop distances) computed using
  relationships that did not exist at the snapshot time.

**Test:** For each user with label=1, compute the number of distinct feature values across all
snapshot dates. If >90% of feature columns show zero variance across dates for label=1 users while
label=0 users show normal variance, flag A1.

### Gate B — Label Purity

**Definition:** The training label must not be a direct function of any input feature. Label
information must not flow into feature computation.

**Violation indicators:**
- A4: Status leakage — the blacklist status field (user_info.status) or any direct derivative is
  used as a feature.
- A5: Blacklist propagation leakage — features like blacklist_1hop_count and blacklist_2hop_count
  encode the label for neighbors, creating a transitive label shortcut.

**Test:** Check for any feature column whose name contains 'blacklist' and 'hop'. These columns
are label shortcuts because they encode whether a user's neighbors are in the ground-truth label
set.

### Gate C — Sample Purity

**Definition:** Each independent unit of observation (user) must appear at most once in any
evaluation set. Duplicate snapshots for the same user with identical feature vectors constitute
pseudo-replication that inflates effective sample size and distorts metrics.

**Violation indicators:**
- A2: Duplicate sample inflation — the same user appears multiple times in the training set with
  identical or near-identical feature vectors, inflating the effective positive sample count.

**Test:** Count appearances per user_id. If max(count) > 2, flag A2. For blacklisted users,
additionally check if the coefficient of variation across feature columns is near zero.

### Gate D — Graph Purity

**Definition:** Graph-derived features must reflect the actual graph topology at snapshot time,
not an inflated or contaminated topology.

**Violation indicators:**
- A7: Graph cardinality explosion — shared_device_count or component_size values are implausibly
  large (e.g., tens of thousands), suggesting all blacklisted users were placed in a single
  artificially-connected component.

**Test:** Check max(shared_device_count) and max(component_size). If either exceeds 10,000, flag
A7 as suspicious. Additionally, check what fraction of blacklisted users share the single largest
component.

### Gate E — Observation Purity

**Definition:** The positive class (blacklisted users) must have observable behavioral signal.
If all positive samples have zero behavioral activity, the model cannot learn genuine AML patterns;
it can only learn that inactivity correlates with blacklist status, which is an artifact of how
the dataset was constructed rather than a genuine risk signal.

**Violation indicators:**
- A3: Inactivity-blacklist shortcut — blacklisted users have all-zero behavioral features
  (fiat_in_30d=0, trade_count_30d=0, crypto_withdraw_30d=0), meaning the model learns
  "zero activity = suspicious" rather than learning fraud patterns.
- A8: Missingness as suspicious — NaN/zero imputation pattern differs systematically between
  positive and negative classes.

**Test:** Compute the fraction of label=1 users with ALL behavioral features == 0. If >95%
of positives are all-zero while <30% of negatives are all-zero, flag A3.

---

## Part 2: Benchmark Families (B1–B8)

### B1 — Snapshot-Level Evaluation (INVALID due to A1+A2)
Evaluate all snapshot-level rows including duplicates. Results are inflated by pseudo-replication.
Report only to document artifact magnitude.

### B2 — User-Level Deduplication (baseline honest)
Deduplicate to one row per user (latest snapshot). This is the minimum requirement for honest
reporting. n=2,832 users, 1,608 positives, 1,224 negatives.

### B3 — Active-Only Cohort (primary honest benchmark)
Restrict to users with fiat_in_30d > 0 OR trade_count_30d > 0. Tests whether models can detect
anomalies in users with real behavioral data, not just dormant accounts.

### B4 — Dormant-Only Cohort
Restrict to users with fiat_in_30d == 0 AND trade_count_30d == 0 AND crypto_withdraw_30d == 0.
Tests whether the dormancy heuristic is the sole driver of results.

### B5 — Temporal Holdout
Strictly time-ordered: train on dates T1..T_k, test on T_{k+1}..T_n. Prevents temporal leakage
in multi-snapshot evaluations.

### B6 — Component Holdout
Separate users by graph component size. Train on small-component users (component_size < 100),
test on large-component users (component_size >= 100). Tests whether the giant component is a
genuine signal or an artifact of shared component membership.

### B7 — Operational Top-K Precision
Report P@50, P@100, P@200, P@500: fraction of true positives among the top-K ranked users.
This is the operationally relevant metric for investigator workload prioritization.

### B8 — Negative Controls
Three negative controls to bound expected performance:
- Prevalence baseline: PR-AUC = positive_rate (random classifier)
- Bootstrap random: mean PR-AUC over 100 random score permutations
- Dormancy heuristic: score = 1.0 if ALL behavioral features == 0, else 0.0
  (tests whether inactivity alone explains results without any model)

---

## Part 3: Cohort Definitions (C1–C10)

| ID  | Name              | Filter condition                                                                  |
|-----|-------------------|-----------------------------------------------------------------------------------|
| C1  | all_users         | No filter — all 2,832 user-level deduplicated rows                               |
| C2  | active_7d         | fiat_in_7d > 0 OR (trade_count_30d > 0 AND fiat_in_7d column present)           |
| C3  | active_30d        | fiat_in_30d > 0 OR trade_count_30d > 0                                           |
| C4  | dormant_30d       | fiat_in_30d == 0 AND trade_count_30d == 0 AND crypto_withdraw_30d == 0           |
| C5  | level2_eligible   | kyc_level >= 2                                                                    |
| C6  | internal_transfer | fan_out_ratio > 0 (has outbound connections)                                      |
| C7  | external_crypto   | crypto_withdraw_30d > 0 (has crypto withdrawals)                                  |
| C8  | api_trading       | trade_count_30d > 0 (proxy for active trading)                                   |
| C9  | graph_connected   | component_size > 10 (part of non-trivial graph component)                         |
| C10 | graph_isolated    | component_size <= 10 (isolated or in tiny component)                              |

---

## Part 4: Metrics Required Per Layer

For every module evaluation, report:

**Classification metrics (user-level, deduplicated):**
- PR-AUC (average precision score)
- Baseline PR-AUC (= positive rate)
- Lift over baseline (= PR-AUC - baseline)
- P@50, P@100, P@200, P@500 (precision at top-K)
- Mann-Whitney U statistic and p-value (score distribution separation)

**Gate status:**
- Each gate: PASS / FAIL / SUSPICIOUS with explanation
- List of triggered artifact codes (A1–A10)
- Result validity: VALID / INVALID / CAUTION

**Cohort breakdown:**
- Results on C1 (all), C3 (active), C4 (dormant)
- Note if performance collapses on active-only cohort

---

## Part 5: Artifact Detector Specifications

| Code | Name                          | Detection method                                                        |
|------|-------------------------------|-------------------------------------------------------------------------|
| A1   | future_snapshot_backfill      | Zero variance in feature cols for label=1 across snapshot dates        |
| A2   | duplicate_sample_inflation    | max(user appearances) > 2                                              |
| A3   | inactivity_blacklist_shortcut | >95% of positives have all-zero behavioral features                    |
| A4   | status_leakage                | 'status' column present in feature set                                 |
| A5   | blacklist_propagation_leakage | 'blacklist_*hop*' columns present in feature set                      |
| A6   | future_graph_leakage          | Graph features computed at a later date used for earlier snapshots     |
| A7   | graph_cardinality_explosion   | max(shared_device_count) > 10,000 or max(component_size) > 10,000     |
| A8   | missingness_as_suspicious     | NaN/zero pattern differs >50% between positive and negative class      |
| A9   | test_fold_threshold_tuning    | Threshold chosen on test set (not separate validation set)             |
| A10  | contaminated_anomaly_training | IForest trained on data including known positives                      |

---

## Part 6: Definition of Invalid Result

A result is **INVALID** if ANY of the following conditions hold:
1. Gate A fails (A1 or A6 triggered): temporal contamination present
2. Gate C fails (A2 triggered): sample duplication inflates metrics
3. Gate E fails (A3 triggered): inactivity shortcut drives classification
4. Any label-shortcut feature (A5) is included in the model's feature set
5. The model is an anomaly detector trained on contaminated data (A10)

A result is **CAUTION** if:
1. Gate B fails (A5 triggered) but label-shortcut features are excluded from scoring
2. Gate D is SUSPICIOUS (A7) but the giant component may reflect real coordination
3. The result relies on dormant-only users and has not been tested on active users

A result is **VALID** only if all five gates PASS or are SUSPICIOUS-but-explained, and the
evaluation uses user-level deduplication (B2 or better).
