# GRAPH_TRUST_BOUNDARY.md

## Graph Feature Trust Boundary

**Status: Graph features are SPLIT — some are trusted, most are disabled by default.**

This document defines which graph features may be used in the BitoGuard pipeline and under what conditions. The distinction between TRUSTED and UNTRUSTED/DISABLED features exists because the current entity-edge dataset contains a critical data quality defect (Artifact A7: placeholder device super-node) that invalidates the majority of graph-derived features.

---

## Configuration Flag

```bash
BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true   # default
```

When this flag is `true` (the default), the pipeline will compute only the TRUSTED graph features listed below. UNTRUSTED features will not be computed or stored. Any model that requires an UNTRUSTED feature will raise a configuration error at startup.

Set to `false` only after completing the full Graph Recovery Plan documented in `docs/GRAPH_RECOVERY_PLAN.md` and passing all four M5 audit checks.

---

## Section 1: TRUSTED Graph Features

These features are safe to compute and use **if the underlying edge data has been rebuilt from validated device IDs**. They carry no super-node contamination risk and do not encode label information.

### 1.1 `fan_out_ratio`

**Definition:** The ratio of unique destination addresses to total outgoing crypto transfers for a user.

```
fan_out_ratio = unique_destination_addresses / total_outgoing_crypto_transfers
```

A value near 1.0 means every transfer goes to a unique address (typical of money-mule fan-out patterns). A value near 0.0 means the user sends to the same small set of addresses repeatedly (typical of legitimate repeated payments).

**Why trusted:**
- Computed from wallet-level transfer records, not device linkage.
- No super-node risk: each transfer has its own destination address; no single destination address artificially links large fractions of the population.
- Does not encode blacklist membership directly.

**Caveats:**
- In the current dataset, `shared_wallet_count` is zero for all users (all wallets are unique), limiting the graph utility of wallet-based features. `fan_out_ratio` is more useful because it measures behavior rather than structural overlap.

---

### 1.2 `shared_device_count` (CONDITIONALLY TRUSTED — requires clean data)

**Definition:** Number of other users who have been linked to the same device fingerprint(s) as this user.

**Current status: DISABLED** (see Section 2). Will become TRUSTED only after the Graph Recovery Plan is executed and all placeholder device IDs are purged from the edge table.

When rebuilt from clean data:
- A high `shared_device_count` indicates device-sharing behavior, which is a meaningful risk signal for account takeover and ring fraud.
- The threshold for "elevated" sharing should be calibrated against the cleaned population distribution.

---

### 1.3 `shared_wallet_count`

**Definition:** Number of other users sharing at least one blockchain wallet address with this user.

**Why trusted:**
- In the current dataset, all wallet addresses are unique per user: `shared_wallet_count = 0` for every user.
- This means the feature carries **no predictive signal**, but it also introduces **no artifact**.
- It is safe to include as a zero-valued feature placeholder for future datasets where wallet sharing occurs.

**Note:** Zero signal is not the same as invalid signal. This feature is trusted but currently non-informative. Monitor with each new data release.

---

## Section 2: UNTRUSTED / DISABLED Features

These features are disabled by default and must not be used in any production scoring, model training, or evaluation until the conditions in Section 3 are met.

### 2.1 `shared_device_count` (in current dataset)

**Disabled reason: Artifact A7 — Placeholder device super-node.**

The current entity_edges table contains a placeholder device ID:

```
dev_cfcd208495d565ef66e7dff9f98764da
```

This value is the MD5 hash of the string `"0"` and was created when null or empty device_id values were hashed during ingestion. This single node connects **46,730 users** — approximately 78% of the entire user population (59,925 total users).

Consequences:
- Any user with a null device_id at ingestion time is falsely linked to 46,729 other users.
- `shared_device_count` is inflated to ~46,730 for the majority of users, regardless of actual device-sharing behavior.
- The feature is not predictive of blacklist status; it is predictive of whether a user had a null device_id at ingestion time.
- All downstream graph metrics that incorporate this edge are compromised.

**Action: Do not compute. Do not train on. Do not evaluate against. Do not expose in API.**

---

### 2.2 `component_size`

**Disabled reason: Inflated by the same placeholder super-node (Artifact A7).**

Graph connected components are formed by following device-sharing edges. Because `dev_cfcd208495d565ef66e7dff9f98764da` links 46,730 users into a single connected component, `component_size` for those users is reported as 46,730 rather than a meaningful cluster size.

A legitimate ring of 10 fraudulent accounts sharing a real device would have `component_size = 10`. In the current dataset, those same users would have `component_size = 46,730` due to the super-node merger.

**Action: Do not compute. The value is meaningless until the super-node is removed and graphs are rebuilt.**

---

### 2.3 `blacklist_1hop_count`

**Disabled reason: Artifact A5 — Direct label leakage through graph.**

`blacklist_1hop_count` counts the number of blacklisted users within one hop (same device or wallet) of the target user. If user A shares a device with user B, and B is blacklisted, then A's `blacklist_1hop_count >= 1`.

This is **label leakage**: the feature encodes information about the blacklist label of neighboring users. Training a classifier with this feature teaches the model to identify users who are adjacent to known-bad users, which is circular when the test set is drawn from the same population.

Correct usage would require:
- A strict temporal holdout where test users' neighbors were not in the training blacklist at the time of prediction.
- Or removal of the feature entirely.

In the current dataset, no such temporal holdout is possible (no onset timestamps exist). This feature is therefore invalid for any evaluation claimed to measure generalization.

**Action: Set `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true` to skip computation entirely.**

---

### 2.4 `blacklist_2hop_count`

**Disabled reason: Artifact A5 — Indirect label leakage through graph.**

Same issue as `blacklist_1hop_count` but two hops removed. The leakage is attenuated but still present and sufficient to inflate model metrics.

In the M5 audit, G1 (full feature set including 1hop/2hop) showed near-perfect apparent performance, while G2 (blacklist-hop features stripped) dropped to ROC-AUC=0.3996 — confirming that essentially all signal in M5 originated from label leakage, not genuine topology.

**Action: Disabled. Same conditions apply as 2.3.**

---

## Section 3: Activation Conditions

UNTRUSTED features may only be re-enabled after **all** of the following conditions are satisfied:

1. The Graph Recovery Plan (`docs/GRAPH_RECOVERY_PLAN.md`) has been fully executed.
2. All M5 audit checks pass:
   - G2 shortcut-free: ROC-AUC > 0.65
   - G3 placeholder-stripped: ROC-AUC > 0.60
   - G4 component holdout: ROC-AUC > 0.65 on balanced holdout
   - G6 marginal over dormancy: ROC-AUC gain > +0.05
3. The audit script `scripts/m5_graph_honest_audit.py` outputs `VALID_MAIN_SIGNAL` or `CONDITIONAL_MAIN_SIGNAL`.
4. A data quality report confirms zero placeholder device IDs remain in the entity_edges table.
5. The change is reviewed and approved before updating `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=false` in production config.

---

## What Constitutes a Trusted Graph Key

A device_id is considered trusted if and only if it meets all of the following criteria:

- **Non-null:** The raw value is not NULL, empty string `""`, or whitespace-only.
- **Non-placeholder literal:** Not `"0"`, `"unknown"`, `"null"`, `"None"`, `"N/A"`, or similar sentinel strings.
- **Non-MD5-of-placeholder:** Not `dev_cfcd208495d565ef66e7dff9f98764da` (MD5 of `"0"`) or the MD5 of any other known sentinel.
- **Format-valid:** Matches the expected device fingerprint format (implementation-specific; typically a UUID or hex string of fixed length).
- **Uniqueness check passed:** Not shared by more than the super-node threshold of users (see below).

Validation is enforced by data quality guards in `bitoguard_core/pipeline/rebuild_edges.py`. See `docs/DATA_QUALITY_GUARDS.md` for full guard specifications.

---

## Super-Node Threshold

> **Any single node connecting more than 1% of the user population must be flagged and excluded from graph construction.**

For a population of 59,925 users, the threshold is **600 users per node**.

A super-node at this scale distorts:
- Component size metrics (all users in the component inherit the inflated size)
- Shared-device counts (all users in the component share the inflated count)
- Graph-propagated risk scores (a single high-risk user in the super-node contaminates all 46,730 neighbors)

The super-node check is implemented in `bitoguard_core/features/graph_features.py` within `build_graph_features()`. If a super-node is detected, the function logs a warning to `ops.data_quality_issues` and, depending on configuration, either skips that node entirely or raises an exception.

```python
SUPER_NODE_THRESHOLD_PCT = 0.01  # 1% of user population
```

---

## Summary Table

| Feature | Status | Safe to Use | Reason |
|---------|--------|-------------|--------|
| `fan_out_ratio` | TRUSTED | Yes | Wallet behavior, no super-node risk |
| `shared_wallet_count` | TRUSTED (zero signal) | Yes | Safe but uninformative currently |
| `shared_device_count` | DISABLED | No | A7 placeholder super-node (46,730 users) |
| `component_size` | DISABLED | No | Inflated by same super-node |
| `blacklist_1hop_count` | DISABLED | No | A5 label leakage |
| `blacklist_2hop_count` | DISABLED | No | A5 label leakage |

---

## References

- `docs/GRAPH_RECOVERY_PLAN.md` — step-by-step plan to re-enable disabled features
- `docs/DATA_QUALITY_GUARDS.md` — guard specifications for device ID validation
- `docs/GRAPH_HONESTY_AUDIT.md` — full M5 audit results including G1–G6
- `bitoguard_core/features/graph_features.py` — feature computation
- `bitoguard_core/pipeline/rebuild_edges.py` — edge validation and construction
- `scripts/m5_graph_honest_audit.py` — audit script
