# DORMANCY_BASELINE.md

## The M0 Dormancy Baseline

**Status: VALID — Primary honest baseline. Every module must beat this to claim signal.**

---

## What Is the M0 Dormancy Baseline?

The M0 dormancy baseline is a single-rule heuristic: a user is classified as **suspicious (score = 1.0)** if and only if all five behavioral features in their 30-day snapshot are exactly zero.

The five features checked are:

| Feature | Description |
|---------|-------------|
| `fiat_in_30d` | Total fiat deposits in the last 30 days |
| `fiat_out_30d` | Total fiat withdrawals in the last 30 days |
| `trade_notional_30d` | Total trade notional volume in the last 30 days |
| `crypto_withdraw_30d` | Total crypto withdrawal amount in the last 30 days |
| `trade_count_30d` | Number of trades executed in the last 30 days |

A user with all five at zero has exhibited **zero behavioral activity** in the observation window. In the BitoGuard dataset, dormant accounts are highly concentrated among blacklisted users, making this the single strongest contemporaneous discriminator available.

### Implementation

```python
# bitoguard_core/models/dormancy.py

BEHAVIORAL_FEATURES = [
    "fiat_in_30d",
    "fiat_out_30d",
    "trade_notional_30d",
    "crypto_withdraw_30d",
    "trade_count_30d",
]

def dormancy_score(row: dict) -> float:
    """Return 1.0 if all behavioral features are zero, else 0.0."""
    total = sum(float(row.get(f, 0.0) or 0.0) for f in BEHAVIORAL_FEATURES)
    return 1.0 if total == 0.0 else 0.0
```

The Python reference module is `bitoguard_core/models/dormancy.py`.

---

## Why This Baseline Matters

### Evaluation Results

| Metric | Value |
|--------|-------|
| PR-AUC | **0.9823** |
| ROC-AUC | **0.9882** |
| F1 | 0.991 |
| Precision | 0.982 |
| Recall | 1.000 |

These results were obtained on a **clean anchor-per-user test set** (one snapshot per user, deduplicated) to prevent data leakage.

The dormancy baseline is the **honest primary baseline** for this dataset because:

1. **It is the floor, not the ceiling.** Any module that cannot beat PR-AUC=0.9823 and ROC-AUC=0.9882 is adding noise, not signal, relative to this trivial rule.
2. **It requires no training.** There are no learned parameters, no risk of overfitting, and no distribution shift to worry about.
3. **It is fully interpretable.** A compliance officer can audit a flagged account immediately: zero activity for 30 days.
4. **It exposes the nature of the labeled data.** The fact that a zero-feature rule achieves 0.98+ PR-AUC reveals that the blacklisted users in this dataset are predominantly dormant, not actively behaving anomalously. This is critical information for scoping what the system can and cannot claim.

---

## Which Modules Beat the Dormancy Baseline?

| Module | PR-AUC | Beats Baseline? | Notes |
|--------|--------|-----------------|-------|
| M0 Dormancy (this baseline) | 0.9823 | N/A | Reference floor |
| M1 Behavioral Rules | 0% trigger rate | NO | Cannot fire on dormant users |
| M2 Statistical Features | INVALID | NO | Invalidated by artifacts A1+A2+A3 |
| M3 LightGBM | INVALID | NO | Invalidated by artifacts A1+A2+A3 |
| M4 IsolationForest | 0.9724 | NO (−0.0099) | Valid signal, below dormancy PR-AUC; ROC-AUC valid |
| M5 Graph Topology | INVALID | NO | Artifact-driven (A7 placeholder super-node) |

**Only M4 IsolationForest produces a valid, non-artifact signal**, and it still does not exceed the dormancy baseline in PR-AUC terms. M4 achieves ROC-AUC gain that is meaningful and is considered VALID WITH CAVEAT.

---

## Why This Is the Honest Primary Baseline

The BitoGuard dataset reflects a **contemporaneous cross-section**: each user snapshot captures their behavioral state at the time the data was exported. The blacklist labels reflect known-bad users at that same point in time.

Given this structure:
- There are **no onset timestamps** indicating when a user first became blacklisted.
- There is **no forward-looking temporal window** available for predictive modeling.
- The dominant signal in the labeled data is **behavioral dormancy at snapshot time**, not early behavioral anomalies preceding fraud.

This means the dataset is well-suited for **contemporaneous screening** (identifying currently dormant/blacklisted users) but does **not support claims of predictive or early-warning behavioral fraud detection**.

The dormancy baseline makes this explicit and quantifiable.

---

## Limitations

1. **Contemporaneous screening only, not predictive detection.** Dormancy is observed at the same time as the blacklist label. This is not a leading indicator.
2. **Recall = 1.000 does not mean zero false negatives in production.** If a blacklisted user transacts even once in 30 days, this rule will miss them. In the current dataset, essentially all blacklisted users are dormant, but production data may differ.
3. **Not a fraud signal per se.** Dormancy is a necessary but not sufficient condition for the type of accounts in this dataset. A legitimate user on sabbatical would also be flagged.
4. **Threshold-free.** The score is binary (0 or 1). A soft score combining dormancy with other features is preferable in production for prioritized queuing.
5. **30-day window is fixed.** Different observation windows (7d, 90d) may produce different results and should be evaluated.

---

## How to Use in Production

### As a First-Pass Filter

The dormancy baseline is the recommended first-pass filter in the BitoGuard detection pipeline:

```
All users
    → dormancy_score() == 1.0  →  "Dormant account queue" → Compliance review
    → dormancy_score() == 0.0  →  M4 anomaly score        → Risk tier assignment
```

Dormant users flagged by M0 should be routed to a compliance review queue. No further model scoring is needed for them — M4 IsolationForest adds only marginal lift (+0.016 PR-AUC) on top of M0, and that lift may not justify the added complexity in a triaged workflow.

### Integration Point

```python
from bitoguard_core.models.dormancy import dormancy_score

score = dormancy_score(user_feature_row)
if score == 1.0:
    route_to_compliance_queue(user_id, reason="dormant_account")
else:
    score = m4_isolation_forest_score(user_feature_row)
    assign_risk_tier(user_id, score)
```

### Batch Evaluation

```python
import pandas as pd
from bitoguard_core.models.dormancy import BEHAVIORAL_FEATURES

df["dormancy_score"] = (df[BEHAVIORAL_FEATURES].sum(axis=1) == 0).astype(float)
```

---

## Claim Validity Standard

> **Any module claiming to beat the BitoGuard system must demonstrate:**
> - PR-AUC > 0.9823
> - ROC-AUC > 0.9882
> - Evaluation on a **clean anchor-per-user test set** (one snapshot per user, no snapshot-level leakage)
> - No label leakage through graph features (blacklist_1hop/2hop must be excluded)
> - No super-node artifacts (device ID placeholder must be resolved)

Claims that do not meet all five conditions are not valid comparisons against this baseline.

---

## References

- `bitoguard_core/models/dormancy.py` — implementation
- `bitoguard_core/models/validate.py` — evaluation harness
- `docs/EVALUATION_PROTOCOL.md` — test set construction protocol
- `docs/EVALUATION_REPORT.md` — full evaluation report with all module results
- `docs/MODEL_CARD.md` — model cards for M0–M6
