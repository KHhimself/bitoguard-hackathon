# Layer Capability Summary

**Evaluation date:** 2026-03-12
**Protocol:** BitoGuard 6-Layer Honest Evaluation Protocol
**Dataset:** 2,832 users (user-level deduplicated, latest snapshot per user)

---

## 1. Key Findings

### What Works (Honest Signal)

**M4 IsolationForest (VALID)**
- PR-AUC = **0.9724** vs baseline 0.5678 (lift = +0.4046)
- Mann-Whitney p = 0.0000e+00 (extremely significant)
- Blacklisted users score -0.125 vs clean -0.155 on anomaly scale
- Active-cohort PR-AUC: N/A (insufficient active positives)
- Trained on clean users only (avoids A10 contamination artifact)
- **Conclusion: Genuine signal. Blacklisted users are behavioral outliers.**

**M5 Graph Topology (CAUTION)**
- LogReg PR-AUC = 0.9643 (suspicious — likely dominated by giant component)
- shared_device_count: blacklisted median = 46,729 vs clean = 0
- component_size: blacklisted median = 69,440 vs clean = 24
- shared_bank_count: p = 0.9999 (NO SIGNAL)
- Giant component contains 91.8% of blacklisted users → A7 artifact
- **Conclusion: Topology contains real signal but graph construction needs audit.**

### What Does NOT Work

**M1 Behavioral Rules (CAUTION)**
- Behavioral-only PR-AUC = 0.5678 ≈ random baseline 0.5678
- ALL 8 behavioral rules fire 0% or near-0% on blacklisted users
- Reason: A3 artifact — blacklisted users have zero behavioral activity
- Label-shortcut rules (blacklist_1hop, blacklist_2hop) show high precision but are data shortcuts
- **Conclusion: Rules cannot fire on dormant users; system needs redesign for dormancy detection.**

**M2 Behavioral Features (INVALID)**
- PR-AUC = 1.0000 (INVALID due to A1+A2+A3)
- Active-cohort PR-AUC = N/A
- **Conclusion: Do not report this result; all signal is artifact-driven.**

**M3 LightGBM Supervised (INVALID)**
- PR-AUC = 1.0000 (INVALID due to A1+A2+A3)
- Top feature: fiat_in_30d_peer_pct (100.00% of gain importance)
- Model learned: KYC income profile + zero activity = blacklisted
- **Conclusion: Not genuine fraud detection; do not deploy without clean data.**

---

## 2. Artifact Summary

| Artifact | Status | Impact |
|----------|--------|--------|
| A1 Future snapshot backfill | TRIGGERED | Invalidates temporal evaluation for M2/M3 |
| A2 Duplicate sample inflation | TRIGGERED | Inflates metric for M2/M3 |
| A3 Inactivity shortcut | TRIGGERED | Model learns dormancy not fraud |
| A5 Blacklist hop leakage | TRIGGERED | Shortcut rules in M1 |
| A7 Graph cardinality explosion | TRIGGERED | Giant component may be synthetic |
| A10 Contaminated anomaly training | TRIGGERED | Fixed by clean-only IForest training |

---

## 3. Recommended Actions

1. **Deploy M4 IForest** for contemporaneous risk screening (not forward prediction)
2. **Audit graph construction** to verify shared_device_count is not artificially inflated
3. **Redesign behavioral rules** to fire on dormant-user patterns (KYC mismatch, unusual registration)
4. **Collect behavioral data** for blacklisted users before retraining supervised models
5. **Do not claim forward prediction** capability — label timestamps are not available

---

## 4. Operational Recommendation

For investigator prioritization, use M4 IForest top-K output:
- P@50 = 0.9200 — of the top 50 users, 92.0% are blacklisted
- P@100 = 0.9500
- P@200 = 0.9750
- P@500 = 0.9820

This represents a genuine lift over random prioritization at every K value.
