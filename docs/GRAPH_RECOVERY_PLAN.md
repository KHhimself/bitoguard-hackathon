# GRAPH_RECOVERY_PLAN.md

## Graph Recovery Plan: Restoring M5 Graph Signal

**Status: REQUIRED before graph features can be used in production.**

This document provides the step-by-step plan to recover valid graph signal after the discovery of Artifact A7 (placeholder device super-node). The current M5 graph module is **QUARANTINED** and must not be used in any production scoring until all steps in this plan are completed and all four audit checks pass.

---

## Background

The M5 graph module was found to produce **INVALID_SIGNAL** in the honest audit (`scripts/m5_graph_honest_audit.py`). The root cause is a single placeholder device ID — `dev_cfcd208495d565ef66e7dff9f98764da` (MD5 of `"0"`) — that was created when null or empty device_id values were hashed during ingestion. This node connects 46,730 users (approximately 78% of the population) into a false super-cluster.

After stripping the placeholder node, the graph model's ROC-AUC drops to **0.3996**, which is worse than random (0.5). The model inverts signal rather than detecting fraud. The marginal gain of the graph over the dormancy baseline is **−0.60 ROC-AUC**, meaning the graph model actively degrades detection performance.

The M5 audit checks that must pass before re-enabling graph features:

| Check | ID | Required Threshold | Current Value |
|-------|----|--------------------|---------------|
| Shortcut-free (no label leakage) | G2 | ROC-AUC > 0.65 | 0.40 (FAIL) |
| Placeholder-stripped | G3 | ROC-AUC > 0.60 | 0.40 (FAIL) |
| Component holdout (balanced) | G4 | ROC-AUC > 0.65 | untested |
| Marginal gain over dormancy | G6 | ROC-AUC gain > +0.05 | −0.60 (FAIL) |

---

## Step 1: Fix Ingestion — Reject Invalid Device IDs at Sync Time

**Owner:** Data/backend engineer
**Effort:** Low
**File:** `bitoguard_core/pipeline/sync_source.py`

Modify the source sync pipeline to reject any device_id value that is null, empty, or a known placeholder **before** it is written to the database.

### Values to Reject

```python
INVALID_DEVICE_IDS = {
    None,
    "",
    "0",
    "unknown",
    "null",
    "None",
    "N/A",
    "n/a",
    # MD5 sentinels of the above
    "cfcd208495d565ef66e7dff9f98764da",       # MD5("0")
    "dev_cfcd208495d565ef66e7dff9f98764da",   # prefixed form
    "d41d8cd98f00b204e9800998ecf8427e",       # MD5("")
}
```

### Action at Ingestion

When a device_id value matches any of the above:
1. Log a warning: `"[sync_source] Rejected invalid device_id: {value} for user {user_id} — skipping device link."`
2. Do NOT write a row to `entity_links` or `user_device_links` for this (user, device) pair.
3. Record the rejection in `ops.data_quality_issues`:
   ```sql
   INSERT INTO ops.data_quality_issues (table_name, issue_type, detail, detected_at)
   VALUES ('user_device_links', 'invalid_device_id', '{"device_id": "...", "user_id": "..."}', NOW())
   ```
4. Continue processing remaining records — do not abort the sync job.

### Verification

After applying this fix, confirm:
```sql
SELECT COUNT(*) FROM user_device_links WHERE device_id IN (
    '0', 'unknown', 'null', 'None', 'N/A',
    'cfcd208495d565ef66e7dff9f98764da',
    'dev_cfcd208495d565ef66e7dff9f98764da'
);
-- Expected: 0
```

---

## Step 2: Rebuild `entity_edges` from Scratch

**Owner:** Data/backend engineer
**Effort:** Low–Medium
**File:** `bitoguard_core/pipeline/rebuild_edges.py`

Once the source data is clean (or once invalid rows have been manually purged from `user_device_links`), rebuild the entity_edges table from scratch.

### Procedure

```bash
# 1. Truncate the current (contaminated) edge table
PYTHONPATH=. python scripts/rebuild_edges.py --mode=truncate-rebuild

# Or manually:
# TRUNCATE entity_edges;
# Then re-run edge construction from validated user_device_links
```

### Edge Construction Rules

Only create an edge between two users if:
- Both users share a **validated** device_id (passes all guards in Step 1).
- The device_id is shared by no more than `SUPER_NODE_THRESHOLD` users (default: 1% of population = 600 for 59,925 users).
- The edge is not a duplicate of an existing (user_a, user_b, device_id) combination.

### Expected Outcome

After rebuild, the entity_edges table should contain only edges backed by genuine device-sharing relationships. The artificial 46,730-user super-component should no longer exist. Verify:

```sql
SELECT device_id, COUNT(DISTINCT user_id) AS user_count
FROM user_device_links
GROUP BY device_id
ORDER BY user_count DESC
LIMIT 10;
-- No device_id should appear with user_count > 600
```

---

## Step 3: Re-Run Graph Feature Computation

**Owner:** ML/data engineer
**Effort:** Low
**File:** `bitoguard_core/features/graph_features.py`

Re-run `build_graph_features()` on the clean edge set to recompute all graph features.

```bash
PYTHONPATH=. python -c "
from bitoguard_core.features.graph_features import build_graph_features
build_graph_features(snapshot_date='latest', validate_edges=True)
"
```

The `validate_edges=True` flag triggers the super-node check before building the graph. If any node connects more than 1% of users, the function will log a warning and exclude that node.

### What to Check After Recomputation

1. `shared_device_count` distribution: should no longer be dominated by a single large value (~46,730). Most users should have 0 or small values.
2. `component_size` distribution: should show a mix of singletons and small clusters, not one enormous component.
3. Any user with `component_size > 600` should be manually inspected before trusting the value.

---

## Step 4: Re-Run All Four M5 Audit Checks

**Owner:** ML engineer
**Effort:** Medium
**Script:** `scripts/m5_graph_honest_audit.py`

```bash
PYTHONPATH=. python scripts/m5_graph_honest_audit.py
```

All four checks must pass before graph features can be re-enabled.

### G2 — Shortcut-Free Evaluation

**What it tests:** Train and evaluate the graph model with `blacklist_1hop_count` and `blacklist_2hop_count` excluded. This checks whether the graph topology itself (independent of label leakage) provides genuine signal.

**Pass condition:** ROC-AUC > 0.65
**Current value:** 0.40 (FAIL)
**Current status:** Failing because after removing label leakage features, no real graph signal remains given the contaminated edge set.

---

### G3 — Placeholder-Stripped Evaluation

**What it tests:** Remove all edges involving the placeholder device ID `dev_cfcd208495d565ef66e7dff9f98764da` (and any other identified placeholders), then re-evaluate.

**Pass condition:** ROC-AUC > 0.60
**Current value:** 0.40 (FAIL)
**Note:** G3 PR-AUC is reported as 0.9967, which appears excellent, but this is entirely an artifact of the test set being 99.6% positive (holdout was dominated by blacklisted users). A random classifier would achieve PR-AUC = 0.996 on such a set. ROC-AUC = 0.3996 confirms the model inverts signal. Do not report G3 PR-AUC without the companion ROC-AUC.

---

### G4 — Component Holdout on Balanced Set

**What it tests:** Hold out entire connected components (not individual users) into the test set to prevent graph neighborhood leakage between train and test. Evaluate on a balanced holdout (approximately 1:1 positive:negative ratio).

**Pass condition:** ROC-AUC > 0.65
**Current value:** Untested (blocked by contaminated edge set)

Component holdout is required because users in the same connected component share graph features. If some component members are in train and others are in test, the test features are not truly independent of training labels.

---

### G6 — Marginal Gain over Dormancy Baseline

**What it tests:** Compute the gain in ROC-AUC achieved by adding graph features on top of the dormancy baseline score.

```
marginal_gain = ROC-AUC(dormancy + graph) - ROC-AUC(dormancy alone)
```

**Pass condition:** marginal_gain > +0.05
**Current value:** −0.60 (FAIL)
**Interpretation:** The graph features currently make detection worse, not better. The model with graph features performs farther below random than the graph-free baseline.

---

### Passing All Four Checks

The audit script will output one of:

| Output | Meaning |
|--------|---------|
| `VALID_MAIN_SIGNAL` | All 4 checks pass; graph features may be used as primary signal |
| `CONDITIONAL_MAIN_SIGNAL` | G2+G4+G6 pass but G3 marginal; graph usable with caveats |
| `SUPPLEMENTARY_SIGNAL` | Some checks pass; graph useful only as supplementary feature |
| `INVALID_SIGNAL` | One or more checks fail; graph features quarantined |

**Only `VALID_MAIN_SIGNAL` or `CONDITIONAL_MAIN_SIGNAL` unlocks production use.**

---

## Step 5: Re-Enable Graph Features in Production

Only after Step 4 produces `VALID_MAIN_SIGNAL` or `CONDITIONAL_MAIN_SIGNAL`:

1. Update the production configuration:
   ```bash
   BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=false
   ```

2. Re-deploy the pipeline with the updated configuration.

3. Monitor the graph feature distribution in the first post-deployment batch to confirm the super-node is absent.

4. Run the full evaluation suite on the first production snapshot:
   ```bash
   PYTHONPATH=. pytest tests/ -v --include-graph
   ```

5. Update `docs/RELEASE_READINESS_CHECKLIST.md` to reflect the new M5 status.

---

## What Data Is Needed

For the recovery plan to succeed, the data provider must supply:

| Data Element | Current State | Required State |
|-------------|---------------|----------------|
| `device_id` in user_device_links | Null/empty for ~78% of users (hashed to placeholder) | Non-null for all users with device linkage |
| Device fingerprint format | Unknown (values hashed) | Raw fingerprint (UUID, hardware ID, or vendor-specific ID) |
| Bank account linkage | Partially available | Non-null for users with bank accounts linked |
| Wallet addresses | Available, all unique | No change needed |

The minimum requirement is that the data provider populate `device_id` with **real, non-null device fingerprints** for users who have authenticated on a mobile or desktop device. Without this, the graph edge set will be empty and no graph-based detection is possible.

---

## Estimated Difficulty

| Task | Effort |
|------|--------|
| Step 1: Fix ingestion validation | Low (1–2 days) |
| Step 2: Rebuild entity_edges | Low (automated, ~1 hour compute) |
| Step 3: Recompute graph features | Low (automated, ~2 hours compute) |
| Step 4: Re-run audit checks | Medium (depends on data quality; may require iteration) |
| Step 5: Production re-enable | Low (config change + smoke test) |

**Total estimated elapsed time:** 1–2 weeks if the data provider can supply non-null device IDs within 3–5 business days.

If the data provider cannot supply non-null device IDs, graph-based detection is not feasible for this dataset regardless of engineering effort. In that case, M0 (dormancy) and M4 (IsolationForest) remain the recommended production signals.

---

## References

- `docs/GRAPH_TRUST_BOUNDARY.md` — which features are trusted vs disabled
- `docs/DATA_QUALITY_GUARDS.md` — guard implementation specifications
- `docs/GRAPH_HONESTY_AUDIT.md` — full audit results
- `bitoguard_core/pipeline/rebuild_edges.py` — edge construction
- `bitoguard_core/features/graph_features.py` — feature computation
- `scripts/m5_graph_honest_audit.py` — audit script
