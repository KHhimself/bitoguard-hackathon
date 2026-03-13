# DATA_QUALITY_GUARDS.md

## Data Quality Guards

**Status: Guards 1–4 are specified. Guards must be implemented before graph features can be re-enabled.**

This document specifies all data quality guards in the BitoGuard pipeline. These guards exist to prevent data defects from silently corrupting model features and invalidating evaluation results. The guards discovered and documented here were motivated by Artifact A7 (placeholder device super-node), which was not caught at ingestion time and invalidated the entire M5 graph module.

---

## Guard 1: Null/Placeholder Device ID Rejection

**Location:** `bitoguard_core/pipeline/rebuild_edges.py`
**When applied:** At edge construction time, before any row is written to `entity_edges` or `user_device_links`
**Test:** `tests/test_graph_data_quality.py::test_guard1_null_device_rejection`

### Rejected Values

The following values must never be used as a device_id when constructing graph edges:

```python
INVALID_DEVICE_ID_LITERALS = {
    None,
    "",
    " ",
    "0",
    "unknown",
    "null",
    "None",
    "N/A",
    "n/a",
    "NA",
    "na",
}

INVALID_DEVICE_ID_MD5_SENTINELS = {
    # MD5 of the above literals — produced when null values were hashed
    "cfcd208495d565ef66e7dff9f98764da",        # MD5("0")
    "dev_cfcd208495d565ef66e7dff9f98764da",    # prefixed form of MD5("0") — KNOWN PLACEHOLDER
    "d41d8cd98f00b204e9800998ecf8427e",        # MD5("")
    "d8e8fca2dc0f896fd7cb4cb0031ba249",        # MD5("unknown")
    "37a6259cc0c1dae299a7866489dff0bd",        # MD5("null")
}
```

The device ID `dev_cfcd208495d565ef66e7dff9f98764da` is the known bad actor: it connects 46,730 users in the current dataset and is the root cause of the M5 graph module invalidation.

### Validation Logic

```python
def is_valid_device_id(device_id: str | None) -> bool:
    """Return True only if device_id is a non-null, non-placeholder identifier."""
    if device_id is None:
        return False
    stripped = device_id.strip()
    if not stripped:
        return False
    if stripped in INVALID_DEVICE_ID_LITERALS:
        return False
    if stripped in INVALID_DEVICE_ID_MD5_SENTINELS:
        return False
    return True
```

### Action on Rejection

When a device_id fails validation:

1. **Log a warning:**
   ```
   [DataQualityGuard1] Rejected invalid device_id='{value}' for user_id='{uid}' — skipping edge.
   ```

2. **Skip the edge:** Do not insert a row into `entity_edges` or `user_device_links` for this (user_id, device_id) pair.

3. **Record in ops table:**
   ```sql
   INSERT INTO ops.data_quality_issues
       (table_name, issue_type, detail, detected_at)
   VALUES
       ('user_device_links', 'invalid_device_id',
        '{"device_id": "<value>", "user_id": "<uid>"}',
        NOW());
   ```

4. **Do not abort the job.** Continue processing remaining records. The sync job is resilient to individual bad records.

### Monitoring

Query to check for accumulated rejections:
```sql
SELECT issue_type, COUNT(*) AS occurrences, MIN(detected_at), MAX(detected_at)
FROM ops.data_quality_issues
WHERE table_name = 'user_device_links'
GROUP BY issue_type
ORDER BY occurrences DESC;
```

---

## Guard 2: Super-Node Detection

**Location:** `bitoguard_core/features/graph_features.py`, within `build_graph_features()`
**When applied:** During graph construction, after edges are loaded but before any feature is computed
**Test:** `tests/test_graph_data_quality.py::test_guard2_super_node_detection`

### Threshold

```python
SUPER_NODE_THRESHOLD_PCT = 0.01   # 1% of total user population
# For 59,925 users: threshold = 599.25 → effective threshold = 600 users per node
```

Any single node (device_id, wallet_address, or other shared identifier) that connects **600 or more users** (for the current population of 59,925) is classified as a super-node and must be excluded from graph construction.

The 1% threshold is not arbitrary: a legitimate shared device in a corporate or family setting might serve 2–10 users. A shared device serving 600+ users is statistically implausible without being a system artifact or data defect.

### Detection Logic

```python
def detect_super_nodes(edges_df: pd.DataFrame, user_count: int) -> list[str]:
    """Return list of device/node IDs that exceed the super-node threshold."""
    threshold = max(1, int(user_count * SUPER_NODE_THRESHOLD_PCT))
    node_degrees = edges_df.groupby("device_id")["user_id"].nunique()
    super_nodes = node_degrees[node_degrees >= threshold].index.tolist()
    return super_nodes
```

### Action on Detection

1. **Log a warning for each super-node found:**
   ```
   [DataQualityGuard2] Super-node detected: device_id='{node}' connects {count} users
   ({pct:.1f}% of population). Excluding from graph construction.
   ```

2. **Optionally raise a configurable exception:**
   ```python
   if BITOGUARD_SUPER_NODE_RAISE_ON_DETECT:
       raise DataQualityError(f"Super-node detected: {node} connects {count} users")
   ```
   Default: warn only, do not raise. Set `BITOGUARD_SUPER_NODE_RAISE_ON_DETECT=true` to fail fast in CI.

3. **Exclude the node from graph construction.** Filter out all edges involving the super-node before building the NetworkX or DuckDB graph.

4. **Record in ops table:**
   ```sql
   INSERT INTO ops.data_quality_issues
       (table_name, issue_type, detail, detected_at)
   VALUES
       ('entity_edges', 'super_node',
        '{"node_id": "<node>", "user_count": <count>, "threshold": <threshold>}',
        NOW());
   ```

---

## Guard 3: Duplicate Edge Detection

**Location:** `bitoguard_core/pipeline/rebuild_edges.py`
**When applied:** After collecting all (user_id, device_id, snapshot_time) tuples, before inserting into `entity_edges`
**Test:** `tests/test_graph_data_quality.py::test_guard3_duplicate_edge_detection`

### What Constitutes a Duplicate

A duplicate edge is any (user_id, device_id, snapshot_time) combination that appears more than once in the incoming batch. Duplicates can arise from:
- Multiple sync runs processing overlapping time windows.
- Upstream data systems emitting the same event more than once.
- Joining across tables that share a common key without deduplication.

### Detection and Deduplication

```python
def deduplicate_edges(edges_df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate (user_id, device_id, snapshot_time) rows, keep first occurrence."""
    key_cols = ["user_id", "device_id", "snapshot_time"]
    original_count = len(edges_df)
    deduped = edges_df.drop_duplicates(subset=key_cols, keep="first")
    removed = original_count - len(deduped)
    if removed > 0:
        logger.warning(
            f"[DataQualityGuard3] Removed {removed} duplicate edges "
            f"({removed / original_count:.1%} of batch)."
        )
    return deduped
```

### Action on Detection

1. **Log the number of duplicates removed.**
2. **Drop duplicates silently** (keep first occurrence). Do not fail the job.
3. **If duplicates exceed 5% of the batch**, log at ERROR level and record in ops table:
   ```sql
   INSERT INTO ops.data_quality_issues
       (table_name, issue_type, detail, detected_at)
   VALUES
       ('entity_edges', 'high_duplicate_rate',
        '{"duplicate_count": <n>, "batch_size": <m>, "rate_pct": <pct>}',
        NOW());
   ```
4. **Investigate the root cause** if the duplicate rate is consistently above 1%.

---

## Guard 4: Blacklist-Label Node Exclusion in Trusted Graph Mode

**Location:** `bitoguard_core/features/graph_features.py`
**When applied:** During feature computation, before `blacklist_1hop_count` or `blacklist_2hop_count` would be computed
**Test:** `tests/test_graph_data_quality.py::test_guard4_blacklist_hop_exclusion`
**Controlled by:** `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY` environment variable

### Purpose

When `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true` (the default), the pipeline must not compute features that encode blacklist label information in the graph neighborhood. Specifically:

- `blacklist_1hop_count`: number of blacklisted users within 1 hop
- `blacklist_2hop_count`: number of blacklisted users within 2 hops

These features constitute **label leakage** (Artifact A5). They encode the blacklist status of a user's neighbors, which is derived from the same labels used to evaluate model performance. Training on or evaluating with these features produces misleadingly high apparent performance.

### Guard Logic

```python
def build_graph_features(
    snapshot_date: str,
    validate_edges: bool = True,
    trusted_only: bool = None,
) -> pd.DataFrame:
    trusted_only = trusted_only if trusted_only is not None else \
        os.getenv("BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY", "true").lower() == "true"

    features = compute_fan_out_ratio(edges)
    features["shared_wallet_count"] = compute_shared_wallet_count(edges)

    if not trusted_only:
        # Only compute these if guard is explicitly disabled
        features["shared_device_count"] = compute_shared_device_count(edges)
        features["component_size"] = compute_component_size(graph)
        features["blacklist_1hop_count"] = compute_blacklist_hops(graph, labels, hops=1)
        features["blacklist_2hop_count"] = compute_blacklist_hops(graph, labels, hops=2)
    else:
        logger.info(
            "[DataQualityGuard4] BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true: "
            "skipping shared_device_count, component_size, blacklist_1hop_count, "
            "blacklist_2hop_count."
        )

    return features
```

### How to Override (Only for Research/Audit)

```bash
BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=false \
    PYTHONPATH=. python scripts/m5_graph_honest_audit.py --mode=full
```

This override is intended only for running the honest audit checks, not for production use.

---

## Running All Guards as Tests

All four guards have corresponding automated tests:

```bash
PYTHONPATH=. pytest tests/test_graph_data_quality.py -v
```

Expected output:

```
tests/test_graph_data_quality.py::test_guard1_null_device_rejection PASSED
tests/test_graph_data_quality.py::test_guard1_known_placeholder_rejection PASSED
tests/test_graph_data_quality.py::test_guard1_md5_sentinel_rejection PASSED
tests/test_graph_data_quality.py::test_guard2_super_node_detection PASSED
tests/test_graph_data_quality.py::test_guard2_super_node_exclusion_from_graph PASSED
tests/test_graph_data_quality.py::test_guard3_duplicate_edge_detection PASSED
tests/test_graph_data_quality.py::test_guard3_high_duplicate_rate_warning PASSED
tests/test_graph_data_quality.py::test_guard4_blacklist_hop_exclusion_trusted_mode PASSED
tests/test_graph_data_quality.py::test_guard4_blacklist_hop_allowed_untrusted_mode PASSED
```

If any test fails, **do not deploy**. Investigate the root cause before proceeding.

---

## Guard Summary

| Guard | ID | Location | Trigger Condition | Action |
|-------|-----|----------|-------------------|--------|
| Null/placeholder device ID | 1 | rebuild_edges.py | device_id is null, empty, or known sentinel | Skip edge, log warning, record in ops |
| Super-node detection | 2 | graph_features.py | Single node connects >= 1% of users | Exclude node, log warning, record in ops |
| Duplicate edge detection | 3 | rebuild_edges.py | Duplicate (user_id, device_id, snapshot_time) | Drop duplicate, log if >5% rate |
| Blacklist-label exclusion | 4 | graph_features.py | BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true | Skip blacklist hop feature computation entirely |

---

## References

- `docs/GRAPH_TRUST_BOUNDARY.md` — which features are trusted vs disabled
- `docs/GRAPH_RECOVERY_PLAN.md` — step-by-step plan to re-enable disabled features
- `bitoguard_core/pipeline/rebuild_edges.py` — Guards 1, 3
- `bitoguard_core/features/graph_features.py` — Guards 2, 4
- `tests/test_graph_data_quality.py` — automated tests for all guards
- `ops.data_quality_issues` — database table for guard event logging
