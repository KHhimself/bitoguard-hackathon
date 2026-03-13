# Graph Honesty Audit

## Purpose

Determine whether M5 graph/topology features provide genuine, independent signal for AML risk detection on the BitoPro dataset, or whether they are driven by data artifacts.

## Methodology

Four must-pass checks + 7 benchmarks (G0–G6) were run on the one-anchor-per-user training dataset. The key concern is Artifact A7 (cardinality explosion from placeholder device super-node).

## Key Finding: Placeholder Device Super-Node

Device ID `dev_cfcd208495d565ef66e7dff9f98764da` is the **MD5 hash of the string '0'**, a classic sentinel value used when a device_id is null or unavailable. This single node connects **46,730 users** in the graph.

**74.6%** of all blacklisted users appear in `user_device_links` with this placeholder device ID.

As a result:
- `shared_device_count` = 46,729 for most blacklisted users (all connected through fake node)
- `component_size` = 69,440 for all users in the giant component
- `blacklist_1hop_count` and `blacklist_2hop_count` encode label information through the graph (A5: blacklist propagation)

## Benchmark Results

| Benchmark | PR-AUC | Notes |
|-----------|--------|-------|
| G0: Dormancy heuristic | 0.9823 | Trivial zero-activity rule |
| G1: Full topology | 0.9998 | Includes blacklist proximity shortcuts |
| G2: Shortcut-free topology | 0.9998 | No blacklist_1hop/2hop |
| G3: Placeholder-stripped | 0.9967 | shared_device_count zeroed for placeholder users |
| G4: Component holdout | 0.9975 | Trained on small components, tested on giant |
| G5: Wallet/fan-out only | 0.9974 | No device features |
| G6 Dormancy baseline | 1.0000 | Reference |
| G6 Marginal gain (G2 - G0) | -0.6004 | Incremental value of M5 |

## 4 Must-Pass Checks

| Check | Result |
|-------|--------|
| CHECK_CARDINALITY | ❌ FAIL |
| CHECK_G2_SHORTCUT_FREE | ✅ PASS |
| CHECK_G3_PLACEHOLDER_STRIPPED | ❌ FAIL |
| CHECK_G4_COMPONENT_HOLDOUT | ✅ PASS |

## Artifact Inventory

| Artifact | Feature | Severity |
|----------|---------|----------|
| A7: Cardinality explosion | shared_device_count, component_size | CRITICAL |
| A5: Blacklist propagation | blacklist_1hop_count, blacklist_2hop_count | CRITICAL |
| A3: Dormancy shortcut | All M5 features (zero for dormant users) | HIGH |

## Final Verdict: `INVALID_SIGNAL`

Cardinality artifact (A7): placeholder device node connects 46,730 users. After stripping placeholder, G3 PR-AUC = 0.9967, G5 wallet-only PR-AUC = 0.9974. Marginal gain over dormancy = -0.6004. Graph topology does not provide independent signal on this dataset.

## Recommendations

1. **Do not use M5 graph features as-is** in any claimed evaluation.
2. **Fix placeholder device IDs** at ingestion time — reject or impute null device_ids rather than hashing '0' as a sentinel.
3. **Exclude blacklist_1hop_count and blacklist_2hop_count** from supervised model features.
4. **If graph is to be used**, rebuild entity_edges with strict non-null, non-placeholder key validation, then re-evaluate.
5. **M5 recovery path**: With a clean graph (real device fingerprints, real wallet matches), shared_device_count and fan_out_ratio could provide genuine ring-fraud detection.
