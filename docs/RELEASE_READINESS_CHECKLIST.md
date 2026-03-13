# RELEASE_READINESS_CHECKLIST.md

## BitoGuard Release Readiness Checklist

**Version:** 1.0.0-rc1
**Date:** 2026-03-13
**Prepared by:** BitoGuard Core Team

This checklist reflects the **honest** state of every system component and model module as of the current release candidate. Items marked with a PASS checkmark are ready for production deployment. Items marked with a WARNING require caveats and monitoring. Items marked FAIL must not be deployed in production for the stated capability.

---

## System Components

### Infrastructure & Pipeline

| Component | Status | Notes |
|-----------|--------|-------|
| Source ingestion (`sync_source.py`) | PASS | Syncs from Oracle; watermarked; resilient to partial failures |
| Data normalization (`normalize.py`) | PASS | Schema validated; type coercions correct |
| Feature engineering (`build_features.py`) | PASS | Behavioral features computed correctly; dormancy flag accurate |
| Incremental refresh (`refresh_live.py`) | PASS | Watermark-based; no-op on unchanged data; bounded batch size |
| FastAPI serving | PASS | 13 endpoints; health check, scoring, and ops endpoints available |
| Docker packaging | PASS | Dockerfile + compose validated; images build locally |
| CI/CD (GitHub Actions) | PASS | Lint, test, build pipeline configured |
| AWS deployment artifacts | PASS | ECR/ECS/S3 scripts prepared; environment variable contract documented |

---

## Model and Signal Readiness

Each model module is assessed against:
1. **Validity:** Is the signal real (not artifact-driven)?
2. **Honest performance:** Are the metrics computed on a clean, non-leaking test set?
3. **Production safety:** Can it be deployed without misleading users or compliance teams?

---

### M0 Dormancy Baseline

**Status: PASS**

| Metric | Value |
|--------|-------|
| PR-AUC | 0.9823 |
| ROC-AUC | 0.9882 |
| F1 | 0.991 |
| Precision | 0.982 |
| Recall | 1.000 |

The dormancy baseline is valid, reproducible, and fully honest. It is the primary detection signal in the current system. It correctly identifies dormant accounts that match the blacklisted user profile. See `docs/DORMANCY_BASELINE.md` for full specification.

**Deployment recommendation:** Use as first-pass filter. Route dormant users (dormancy_score = 1.0) directly to compliance review queue.

---

### M4 IsolationForest

**Status: PASS WITH CAVEAT**

| Metric | Value | vs. Dormancy Baseline |
|--------|-------|-----------------------|
| PR-AUC | 0.9724 | −0.0099 |
| ROC-AUC | Valid | Marginal gain |

M4 produces a valid, non-artifact anomaly score. It is the **only model module beyond M0** that passes the honest audit. Its PR-AUC is slightly below the dormancy baseline (0.9724 vs. 0.9823), but its continuous score provides useful ranking capability for users that fall between the binary dormancy cutoffs.

**Caveat:** M4 is a contemporaneous detector only. It identifies users whose behavioral profile at snapshot time is anomalous relative to the overall population. It does not provide forward-looking predictions.

**Deployment recommendation:** Use M4 score as a secondary ranking signal for non-dormant users (those with dormancy_score = 0.0). Do not present M4 scores as a substitute for the dormancy baseline; the dormancy baseline has higher PR-AUC.

---

### M1 Behavioral Rules

**Status: FAIL — DO NOT DEPLOY**

M1 behavioral rules require active behavioral signals (non-zero fiat flows, trade activity, crypto withdrawals) to fire. Because the blacklisted users in the current dataset are predominantly dormant (zero behavioral features), M1 achieves a **0% trigger rate** on the labeled population.

The rules are not wrong in principle — they would detect active fraud patterns if such patterns existed in the data — but they cannot be validated on this dataset and cannot claim any detection capability against the current labeled population.

**Deployment recommendation:** Do not deploy for fraud detection claims. Redesign rules to account for the dormancy pattern, or hold until a dataset with behaviorally active fraud cases is available.

---

### M2 Statistical Features

**Status: FAIL — RESULTS INVALIDATED**

M2 results are invalidated by data artifacts A1, A2, and A3:

- **A1:** Feature distribution artifact — certain aggregate statistics are computed across snapshot windows that include blacklisted users, creating distribution shift between labeled classes.
- **A2:** Temporal overlap artifact — snapshot windows are not cleanly separated, allowing future information to leak into historical features.
- **A3:** Normalization artifact — per-feature normalization was applied globally rather than per-training-fold, leaking test set statistics into training.

Any M2 performance metrics reported prior to this audit should be disregarded. Recomputation requires resolving all three artifacts.

**Deployment recommendation:** Do not deploy. Recompute features after resolving artifacts A1, A2, A3 and re-evaluate on a clean test set.

---

### M3 LightGBM

**Status: FAIL — RESULTS INVALIDATED**

M3 LightGBM trained on M2 statistical features. Because the input features are invalidated by artifacts A1+A2+A3, all M3 results are also invalid. This applies to:
- Training metrics (these appear inflated due to leakage)
- Validation metrics (same leakage applies)
- Any feature importance rankings (reflect artifact structure, not genuine predictive relationships)

The LightGBM model must not be used for behavioral fraud prediction claims.

**Deployment recommendation:** Do not deploy for behavioral prediction. After M2 features are fixed and re-validated, M3 may be retrained and re-evaluated.

---

### M5 Graph Topology

**Status: QUARANTINED — DO NOT DEPLOY**

M5 graph module is quarantined due to Artifact A7: the placeholder device ID `dev_cfcd208495d565ef66e7dff9f98764da` (MD5 of `"0"`) connects 46,730 users into a false super-cluster. All graph topology features derived from device-sharing edges are compromised.

Audit results:

| Check | Result | Threshold | Status |
|-------|--------|-----------|--------|
| G2 shortcut-free ROC-AUC | 0.3996 | > 0.65 | FAIL |
| G3 placeholder-stripped ROC-AUC | 0.3996 | > 0.60 | FAIL |
| G4 component holdout ROC-AUC | untested | > 0.65 | BLOCKED |
| G6 marginal gain over dormancy | −0.60 | > +0.05 | FAIL |

The G3 PR-AUC of 0.9967 may appear to contradict the FAIL status, but this figure is **below the random baseline** for a test set that is 99.6% positive. A random classifier achieves PR-AUC = 0.996 on such a set. The companion ROC-AUC = 0.3996 confirms the model inverts signal rather than detecting fraud.

**Deployment recommendation:** Quarantined. Do not compute, serve, or expose graph features until the Graph Recovery Plan (`docs/GRAPH_RECOVERY_PLAN.md`) is completed and all four audit checks pass.

---

### M6 Operations/Refresh

**Status: PASS**

The M6 operations module (incremental refresh, watermark management, feature store updates) is fully functional. It operates correctly on the behavioral feature set and does not depend on the quarantined graph features when `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true`.

---

## Honest System Capabilities

This section states what the BitoGuard system **can** and **cannot** claim as of this release.

### Can Do

| Capability | Evidence |
|-----------|----------|
| Detect dormant accounts matching the blacklist profile | M0: PR-AUC=0.9823, ROC-AUC=0.9882 |
| Rank non-dormant users by behavioral anomaly score | M4 IsolationForest: valid, continuous score |
| Operate incrementally on new data without full recompute | M6 refresh: watermarked, tested |
| Provide reproducible, auditable detection scores | All passing modules have documented test sets |

### Cannot Do

| Claimed Capability | Reason Invalid |
|-------------------|----------------|
| Predict behavioral fraud patterns (early warning) | No behavioral signal in labeled data; blacklisted users are dormant at snapshot time |
| Perform forward prediction / time-to-blacklist estimation | No onset timestamps available; contemporaneous snapshot only |
| Claim graph-based ring/money-mule network detection | M5 quarantined; artifact-driven, not signal-driven |
| Claim supervised behavioral model results | M3 LightGBM results invalid due to A1+A2+A3 artifacts |
| Claim M2 statistical feature validity | Artifacts A1+A2+A3 invalidate all M2 metrics |
| Claim M5 graph PR-AUC=0.9967 as a real performance metric | This figure is below random baseline for 99.6%-positive holdout |

---

## AWS Deployment

| Item | Status | Notes |
|------|--------|-------|
| Docker images build locally | PASS | Tested in CI |
| ECR push scripts available | PASS | `infra/ecr_push.sh` |
| ECS task definitions prepared | PASS | `infra/ecs_task_def.json` |
| Environment variable contract documented | PASS | `deploy/.env.compose.example` |
| Clean production device_ids required for graph | CAVEAT | Graph disabled until device IDs are non-null |
| M3/M5 disabled in production config | REQUIRED | Must set `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true` and disable M3 scoring endpoint |

### Required Environment Variables for Production

```bash
# Required: Graph feature mode (must be true until Graph Recovery Plan completes)
BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true

# Required: Disable quarantined modules
BITOGUARD_M3_ENABLED=false
BITOGUARD_M5_ENABLED=false

# Required: Primary detection modules
BITOGUARD_M0_ENABLED=true
BITOGUARD_M4_ENABLED=true
```

Any production deployment that sets `BITOGUARD_M3_ENABLED=true`, `BITOGUARD_M5_ENABLED=true`, or `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=false` without first completing the Graph Recovery Plan and M2/M3 artifact remediation is considered **unsafe for production**.

---

## Pre-Deploy Checklist (Operator Steps)

Before each production deployment, confirm:

- [ ] `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true` is set in the deployment environment.
- [ ] `BITOGUARD_M3_ENABLED=false` is set.
- [ ] `BITOGUARD_M5_ENABLED=false` is set.
- [ ] `PYTHONPATH=. pytest tests/ -v` passes with no failures.
- [ ] Docker image builds without error: `docker build -t bitoguard-core .`
- [ ] Health check endpoint responds: `GET /health` returns `{"status": "ok"}`.
- [ ] Dormancy baseline produces expected scores on a known test case.
- [ ] `ops.data_quality_issues` is empty or contains only known/resolved issues.
- [ ] Deployment reviewer has read and acknowledged the "Cannot Do" section above.

---

## Conditions for Updating This Checklist

| Change | Required Action Before Updating Status |
|--------|----------------------------------------|
| M1 to PASS | Redesign rules for dormant user population; validate on clean test set |
| M2 to PASS | Resolve artifacts A1, A2, A3; recompute all features; full re-evaluation |
| M3 to PASS | M2 must pass first; then retrain LightGBM on clean features; full re-evaluation |
| M5 to PASS | Complete Graph Recovery Plan; all four G-checks must pass; script outputs VALID_MAIN_SIGNAL |
| Graph features re-enabled | M5 PASS status achieved; production device_ids confirmed non-null |

---

## References

- `docs/DORMANCY_BASELINE.md` — M0 specification
- `docs/GRAPH_TRUST_BOUNDARY.md` — graph feature trust rules
- `docs/GRAPH_RECOVERY_PLAN.md` — M5 recovery steps
- `docs/DATA_QUALITY_GUARDS.md` — guard specifications
- `docs/EVALUATION_REPORT.md` — full audit results for all modules
- `docs/GRAPH_HONESTY_AUDIT.md` — M5 G1–G6 audit details
- `docs/RUNBOOK_AWS.md` — AWS deployment operations
- `deploy/.env.compose.example` — environment variable reference
