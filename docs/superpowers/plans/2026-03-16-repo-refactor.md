# BitoGuard Repo Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make v2 stacker the single canonical pipeline, convert bitoguard_core to a proper Python package, fix the P0 zero-alert bug, and aggressively clean documentation and scripts.

**Architecture:** Six ordered tasks, each independently committable. Tasks 1–2 have no dependencies. Task 3 depends on Task 2 (package must be installed before imports are verified). Tasks 4–6 are independent of each other and of Tasks 1–3.

**Tech Stack:** Python 3.12, setuptools, CatBoost + LightGBM stacker, FastAPI, pytest, DuckDB

**Spec:** `docs/superpowers/specs/2026-03-16-repo-refactor-design.md`

---

## Chunk 1: Tasks 1 and 2

### Task 1: P0 Bug Fixes — Enable M1+M3, Recalibrate Thresholds

**Context:** System currently generates zero alerts. `config.py` has M1 (rules) and M3 (supervised model) disabled by default. `score_latest_snapshot_v2()` has unreachable alert thresholds (max score ≈ 57, threshold at 35). These two file changes unblock the demo immediately.

**Files:**
- Modify: `bitoguard_core/config.py:98-100`
- Modify: `bitoguard_core/models/score.py:317-320`

---

- [ ] **Step 1: Verify current broken state**

```bash
cd bitoguard_core && grep -n "m1_enabled\|m3_enabled\|m4_enabled" config.py
```
Expected output:
```
98:        m1_enabled=_env_flag("BITOGUARD_M1_ENABLED", False),
99:        m3_enabled=_env_flag("BITOGUARD_M3_ENABLED", False),
100:        m4_enabled=_env_flag("BITOGUARD_M4_ENABLED", True),
```

---

- [ ] **Step 2: Fix module defaults in `bitoguard_core/config.py` lines 98–100**

Replace:
```python
        m1_enabled=_env_flag("BITOGUARD_M1_ENABLED", False),
        m3_enabled=_env_flag("BITOGUARD_M3_ENABLED", False),
        m4_enabled=_env_flag("BITOGUARD_M4_ENABLED", True),
```
With:
```python
        m1_enabled=_env_flag("BITOGUARD_M1_ENABLED", True),
        m3_enabled=_env_flag("BITOGUARD_M3_ENABLED", True),
        # M4 explicitly disabled: IsolationForest trained on v1 schema, incompatible with v2.
        # Re-enable after retraining on v2 features (negatives-only). See docs/GRAPH_RECOVERY_PLAN.md.
        m4_enabled=_env_flag("BITOGUARD_M4_ENABLED", False),
```

---

- [ ] **Step 3: Fix alert thresholds in `bitoguard_core/models/score.py` lines 317–320**

Locate the threshold block inside `score_latest_snapshot_v2()`:
```python
    result["risk_level"] = pd.cut(
        result["risk_score"], bins=[-1, 35, 60, 80, 100],
        labels=["low", "medium", "high", "critical"],
    ).astype(str)
```
Replace with:
```python
    # Risk score ceiling with M1+M3 active (no M4/M5):
    # max risk_score = (0.20*rule_score + 0.70*model_prob) * 100 ≈ 57 at best.
    # Thresholds must stay below 57 to produce any alerts. Do not revert to [-1,35,...].
    result["risk_level"] = pd.cut(
        result["risk_score"], bins=[-1, 20, 50, 70, 100],
        labels=["low", "medium", "high", "critical"],
    ).astype(str)
```

---

- [ ] **Step 4: Run tests to verify nothing is broken**

```bash
cd bitoguard_core && source .venv/bin/activate && PYTHONPATH=. python -m pytest tests/ -q
```
Expected: all existing tests pass (the config change only affects defaults, tests use monkeypatching).

---

- [ ] **Step 5: Commit**

```bash
git add bitoguard_core/config.py bitoguard_core/models/score.py
git commit -m "fix: enable M1+M3 by default, recalibrate v2 alert thresholds

M1 (rules) and M3 (supervised model) were off by default, causing
zero alerts. M4 explicitly disabled (schema mismatch with v2 features).
Alert threshold bins recalibrated from [-1,35,60,80,100] to
[-1,20,50,70,100] — max achievable score with M1+M3 is ~57."
```

---

### Task 2: Python Packaging — Add pyproject.toml, Remove PYTHONPATH

**Context:** `bitoguard_core/` is not a proper Python package — it uses `PYTHONPATH=.` in every command. Adding `pyproject.toml` and `pip install -e .` makes imports work in any context (IDE, Docker, tests) without the env var hack. All subdirectory `__init__.py` files already exist — only the root `__init__.py` is missing.

**Files:**
- Create: `bitoguard_core/pyproject.toml`
- Create: `bitoguard_core/__init__.py`
- Modify: `Makefile` (remove `PYTHONPATH=.`, add `pip install -e .` to setup)
- Modify: `bitoguard_core/Dockerfile.processing`
- Modify: `bitoguard_core/Dockerfile.training`

---

- [ ] **Step 1: Verify all subdirectory `__init__.py` files exist**

```bash
find bitoguard_core -name __init__.py | sort
```
Expected: files in `models/`, `features/`, `services/`, `pipeline/`, `api/`, `db/`. If any are missing, create empty files.

---

- [ ] **Step 2: Create `bitoguard_core/__init__.py`** (empty)

```bash
touch bitoguard_core/__init__.py
```

---

- [ ] **Step 3: Create `bitoguard_core/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "bitoguard"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.setuptools.packages.find]
where = ["."]
include = ["bitoguard*", "models*", "features*", "services*",
           "pipeline*", "api*", "db*"]

[tool.pytest.ini_options]
addopts = "-m 'not integration'"
markers = [
    "integration: requires live scored data in bitoguard.duckdb (run manually after make score)",
]
```

---

- [ ] **Step 4: Install the package into the existing venv**

```bash
cd bitoguard_core && source .venv/bin/activate && pip install -e . -q
```
Expected: `Successfully installed bitoguard-0.1.0`

---

- [ ] **Step 5: Verify imports work without PYTHONPATH**

```bash
cd bitoguard_core && source .venv/bin/activate && python -c "from models.common import NON_FEATURE_COLUMNS; print('OK')"
```
Expected: `OK`

---

- [ ] **Step 6: Update `Makefile` — remove `PYTHONPATH=.`, add install to setup**

Replace the entire `setup` target (lines 35–38):
```makefile
setup: ## Create .venv, install Python dependencies, and install package
	cd $(CORE_DIR) && python -m venv .venv && \
	$(ACTIVATE) && pip install -r requirements.txt && pip install -e .
	@echo "Setup complete. Activate with: source bitoguard_core/.venv/bin/activate"
```

Then remove `PYTHONPATH=. ` prefix from every command in the Makefile. The full set of lines to update:

Line 43: `cd $(CORE_DIR) && $(ACTIVATE) && python -m pytest tests/ -v`
Line 46: `cd $(CORE_DIR) && $(ACTIVATE) && python -m pytest tests/ -q`
Line 49: `cd $(CORE_DIR) && $(ACTIVATE) && python -m pytest tests/test_rule_engine.py -v`
Line 54: `cd $(CORE_DIR) && $(ACTIVATE) && python pipeline/sync.py --full`
Line 57–59: features target, both `python` calls
Line 62: `cd $(CORE_DIR) && $(ACTIVATE) && python pipeline/refresh_live.py`
Line 68–69: train target (will be replaced in Task 3)
Line 72: evaluate target (will be deleted in Task 3)
Line 75: `cd $(CORE_DIR) && $(ACTIVATE) && python models/score.py`
Line 78: `cd $(CORE_DIR) && $(ACTIVATE) && python features/build_features_v2.py`
Line 81: `cd $(CORE_DIR) && $(ACTIVATE) && python models/stacker.py`
Line 84–85: score-v2 target (will be deleted in Task 3)
Line 88: `cd $(CORE_DIR) && $(ACTIVATE) && python services/drift.py`
Line 94: `cd $(CORE_DIR) && $(ACTIVATE) && uvicorn api.main:app --reload --port 8001`

---

- [ ] **Step 7: Update `bitoguard_core/Dockerfile.processing` — add package install**

Find the line after `COPY` (or after `pip install -r requirements.txt`) and add:
```dockerfile
RUN pip install -e .
```

---

- [ ] **Step 8: Update `bitoguard_core/Dockerfile.training` — add package install**

Same as Step 7 but for `Dockerfile.training`.

---

- [ ] **Step 9: Run full test suite without PYTHONPATH to verify packaging works**

```bash
cd bitoguard_core && source .venv/bin/activate && python -m pytest tests/ -q
```
Expected: all 85 tests pass.

---

- [ ] **Step 10: Commit**

```bash
git add bitoguard_core/pyproject.toml bitoguard_core/__init__.py Makefile \
        bitoguard_core/Dockerfile.processing bitoguard_core/Dockerfile.training
git commit -m "chore: convert bitoguard_core to proper Python package

Add pyproject.toml (setuptools.build_meta) and root __init__.py.
Remove PYTHONPATH=. from all Makefile targets — package installs
via pip install -e bitoguard_core/ instead."
```

---

## Chunk 2: Tasks 3–6

### Task 3: Delete v1, Wire v2 as Canonical Pipeline

**Context:** The v1 LightGBM pipeline (`models/train.py`, `models/validate.py`) is dead — it OOM-kills on 2.55M rows and the holdout splitter fails with a single snapshot date. The v2 stacker (`score_latest_snapshot_v2`) is never called by the API. This task wires v2 into production and deletes all v1 references.

**Files:**
- Delete: `bitoguard_core/models/train.py`
- Delete: `bitoguard_core/models/validate.py`
- Modify: `bitoguard_core/models/train_catboost.py` (make private names public)
- Modify: `bitoguard_core/models/stacker.py` (fix import)
- Modify: `bitoguard_core/models/score.py` (delete v1 path, rename v2, remove dead code)
- Modify: `bitoguard_core/api/main.py` (update train+score endpoints, fix imports)
- Modify: `bitoguard_core/pipeline/refresh_live.py` (update import)
- Modify: `bitoguard_core/ml_pipeline/train_entrypoint.py` (update import)
- Modify: `bitoguard_core/tests/test_model_pipeline.py` (remove v1-dependent tests)
- Modify: `bitoguard_core/tests/test_stacker.py` (update import)
- Modify: `Makefile` (update train/score/evaluate targets)

---

- [ ] **Step 1: Make private names public in `bitoguard_core/models/train_catboost.py`**

Line 15: rename `_CAT_FEATURE_NAMES` → `CAT_FEATURE_NAMES`
Line 20: rename `_load_v2_training_dataset` → `load_v2_training_dataset`

```python
# Line 15 — before:
_CAT_FEATURE_NAMES = frozenset({
# Line 15 — after:
CAT_FEATURE_NAMES = frozenset({

# Line 20 — before:
def _load_v2_training_dataset() -> "pd.DataFrame":
# Line 20 — after:
def load_v2_training_dataset() -> "pd.DataFrame":
```

---

- [ ] **Step 2: Update import in `bitoguard_core/models/stacker.py` line 24**

```python
# Before:
from models.train_catboost import _load_v2_training_dataset, _CAT_FEATURE_NAMES

# After:
from models.train_catboost import load_v2_training_dataset, CAT_FEATURE_NAMES
```

Also update the two usage sites in `stacker.py`:
- `dataset = _load_v2_training_dataset()` → `dataset = load_v2_training_dataset()`
- `cat_indices = [i for i, c in enumerate(feature_cols) if c in _CAT_FEATURE_NAMES]` → `... if c in CAT_FEATURE_NAMES`

---

- [ ] **Step 3: Update import in `bitoguard_core/tests/test_stacker.py` line 94**

```python
# Before:
from models.train_catboost import _load_v2_training_dataset
# ...
dataset = _load_v2_training_dataset()

# After:
from models.train_catboost import load_v2_training_dataset
# ...
dataset = load_v2_training_dataset()
```

---

- [ ] **Step 4: Verify stacker tests pass before deleting anything**

```bash
cd bitoguard_core && source .venv/bin/activate && python -m pytest tests/test_stacker.py -v
```
Expected: all stacker tests pass.

---

- [ ] **Step 5: Delete v1 files**

```bash
rm bitoguard_core/models/train.py
rm bitoguard_core/models/validate.py
```

---

- [ ] **Step 6: Clean up `bitoguard_core/models/score.py` — delete v1 and dead code**

**Order matters**: delete in this sequence to avoid mid-step test failures.

First, delete `score_latest_snapshot()` (the entire v1 function, lines 97–236). This is the large v1 scoring path.

Then delete `_build_model_version()` (lines 48–65). It is only called by the now-deleted v1 function.

Then delete the dead import at line 12 — `from models.dormancy import dormancy_series` is only used in the deleted v1 function and must be removed. (`dormancy_series` is not called anywhere in `score_latest_snapshot_v2`.)

Then rename `score_latest_snapshot_v2` → `score_latest_snapshot` at line 250:
```python
# Before:
def score_latest_snapshot_v2() -> pd.DataFrame:
# After:
def score_latest_snapshot() -> pd.DataFrame:
```

The `__main__` block at lines 357–358 already reads `print(score_latest_snapshot().head())` and requires **no change** — after the rename, this naturally calls the promoted v2 implementation.

---

- [ ] **Step 7: Update `bitoguard_core/api/main.py` — fix imports and train endpoint**

**Imports** — three changes:

Lines 22–24: replace the train/validate imports:
```python
# Before (lines 22–24):
from models.score import score_latest_snapshot
from models.train import train_model
from models.validate import validate_model

# After:
from models.score import score_latest_snapshot
from models.stacker import train_stacker
```

Line 21: delete the now-dead anomaly import (the `model_train()` body being replaced no longer calls `train_anomaly_model`):
```python
# Before (line 21):
from models.anomaly import train_anomaly_model

# After: delete this line entirely
```

**Train endpoint (lines 360–374)** — replace body:
```python
@app.post("/model/train", dependencies=[Depends(_require_api_key)])
def model_train() -> dict[str, Any]:
    result = train_stacker()
    return {
        "model": result["stacker_version"],
        "stacker_path": result["stacker_path"],
        "branch_models": result["branch_models"],
        "cv_results": result["cv_results"],
    }
```

**Score endpoint (lines 377–380)** — no change needed (already imports `score_latest_snapshot`, which now points to v2 after the rename).

---

- [ ] **Step 8: Update `bitoguard_core/pipeline/refresh_live.py` line 19**

```python
# Before (line 19):
from models.score import score_latest_snapshot

# After: no change needed — the import name is the same after the rename.
# Verify the import is present and the call at line 564 uses score_latest_snapshot().
```

Run: `grep -n "score_latest_snapshot\|train_model\|validate_model" bitoguard_core/pipeline/refresh_live.py`
Expected: only `score_latest_snapshot` references, no `train_model` or `validate_model`.

---

- [ ] **Step 9: Update `bitoguard_core/ml_pipeline/train_entrypoint.py` lines 19–21**

Lines 19–20 import the deleted v1 functions. Line 21 imports `train_anomaly_model` which may or may not still be used in this file. Check with:
```bash
grep -n "train_model\|train_catboost\|train_anomaly\|train_stacker" bitoguard_core/ml_pipeline/train_entrypoint.py
```

Replace the v1 imports:
```python
# Before (lines 19–20):
from models.train import train_model
from models.train_catboost import train_catboost_model as train_catboost

# After:
from models.stacker import train_stacker
```

If `train_anomaly_model` (line 21) is not used after the call-site update below, delete line 21 too.

Find and update the call site (line ~167):
```python
# Before:
result = train_model()

# After:
result = train_stacker()
```

---

- [ ] **Step 10: Fix v1-dependent tests in `bitoguard_core/tests/test_model_pipeline.py`**

**Lines 12, 14–15** — update imports (remove dead imports):
```python
# Before (lines 12, 14–15):
from models.anomaly import train_anomaly_model   # line 12 — only used in deleted test
from models.train import train_model              # line 14
from models.validate import validate_model        # line 15

# After (delete lines 12, 14, 15 entirely; add stacker import):
from models.stacker import train_stacker
```

**Lines 978–980** — delete these three monkeypatch lines. `refresh_live.py` never imports these functions (`raising=False` was the guard) so removing the patch lines is safe:
```python
# Delete:
monkeypatch.setattr(refresh_live_module, "train_model", fail_if_called, raising=False)
monkeypatch.setattr(refresh_live_module, "train_anomaly_model", fail_if_called, raising=False)
monkeypatch.setattr(refresh_live_module, "validate_model", fail_if_called, raising=False)
```

**`test_model_training_and_validation_use_dynamic_forward_splits` (lines 587–608)** — delete this entire test function. It exercises `train_model()` and `validate_model()` which no longer exist.

**`test_validate_model_includes_split_used_in_report` (lines 1067–1072)** — delete this entire test function. It inspects the source code of a deleted function.

---

- [ ] **Step 11: Update Makefile targets**

Replace `train` target — the current target spans 4 lines (66–69). Replace all 4 lines with 2:
```makefile
train: ## Train CatBoost + LightGBM branches + LR stacker (v2 features)
	cd $(CORE_DIR) && $(ACTIVATE) && python models/stacker.py
```

Delete `evaluate` target (lines 71–72, two lines) — no replacement. The stacker's 5-fold CV is the evaluation.

Delete `train-stacker` target (lines 80–81, two lines) — consolidated into `train`.

Delete `score-v2` target (lines 83–85, three lines) — `score` now calls the v2 implementation.

Update the `.PHONY` line (line 24) to remove: `evaluate`, `score-v2`, `train-stacker`.

Update the `help` comment at the top of the Makefile (lines 9–10):
```makefile
#   make train             Train CatBoost + LightGBM stacker (v2 features)
```
Delete the `make evaluate` and `make score-v2` help lines.

---

- [ ] **Step 12: Run full test suite**

```bash
cd bitoguard_core && source .venv/bin/activate && python -m pytest tests/ -q
```
Expected: all remaining tests pass (minus the 2 deleted tests). Count should be ~83 tests.

---

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "feat: make v2 stacker canonical, delete v1 LightGBM pipeline

- Delete models/train.py and models/validate.py (v1, OOM-kills at 2.55M rows)
- Rename score_latest_snapshot_v2 -> score_latest_snapshot
- Wire API /model/train to train_stacker(), /model/score to v2 path
- Make _load_v2_training_dataset and _CAT_FEATURE_NAMES public
- Remove train_model/validate_model monkeypatches from refresh tests
- Consolidate Makefile: train=stacker, delete evaluate/score-v2 targets"
```

---

### Task 4: Scripts Cleanup

**Context:** 23 shell scripts, many empty or duplicating each other. Delete dead scripts; keep only those with a unique, non-overlapping purpose.

**Files:**
- Delete: 9 scripts listed below
- Delete: 6 root-level status markdown files

---

- [ ] **Step 1: Delete empty and redundant scripts**

```bash
rm scripts/launch-5fold-scriptmode.sh      # empty (1 line)
rm scripts/deploy-and-launch-5fold.sh      # duplicate of deploy + launch
rm scripts/deploy-and-train.sh             # duplicate
rm scripts/deploy-infrastructure-first.sh  # subset of deploy-ml-pipeline
rm scripts/deploy-sagemaker-features.sh    # overlaps deploy-sagemaker-only
rm scripts/deploy-sagemaker-only.sh        # overlaps deploy-ml-pipeline
rm scripts/quick-deploy-and-run.sh         # duplicate shortcut
rm scripts/local-train-5fold.sh            # redundant with make train
rm scripts/launch-5fold-training.sh        # redundant with make train
```

---

- [ ] **Step 2: Delete root-level generated status docs**

```bash
rm DEPLOYMENT_CHECKLIST.md
rm DEPLOYMENT_READY.md
rm SAGEMAKER_DEPLOYMENT_READY.md
rm SAGEMAKER_READY.md
rm STACKER_IMPLEMENTATION_COMPLETE.md
rm WORKSHOP_DEPLOYMENT.md
rm DEPLOYMENT_SUMMARY.md
rm README_AWS.md
```

---

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: delete redundant scripts and generated status docs

Remove 9 shell scripts (empty/duplicate/superseded by make targets)
and 6 root-level deployment status files (generated artifacts)."
```

---

### Task 5: Docs Cleanup

**Context:** docs/ has 35 files. Keep 8 essential files; delete 27 others. See explicit lists below.

**Files:**
- Keep: `docs/GRAPH_TRUST_BOUNDARY.md`, `docs/GRAPH_RECOVERY_PLAN.md`, `docs/ML_PIPELINE_SUMMARY.md`, `docs/SAGEMAKER_DEPLOYMENT_GUIDE.md`, `docs/RULEBOOK.md`, `docs/MODEL_CARD.md`, `docs/DATA_CONTRACT.md`, `docs/RUNBOOK_LOCAL.md`
- Delete: all other files in `docs/` except `docs/superpowers/`

---

- [ ] **Step 1: Delete the 27 files not in the keep list**

```bash
cd docs && rm -f \
  AWS_DEPLOYMENT_GUIDE.md \
  COMPLETE_AWS_SAGEMAKER_DEPLOYMENT.md \
  COST_OPTIMIZATION.md \
  DORMANCY_BASELINE.md \
  EVALUATION_PROTOCOL.md \
  EVALUATION_REPORT.md \
  FEATURE_DICTIONARY.md \
  GRAPH_HONESTY_AUDIT.md \
  GRAPH_SCHEMA.md \
  LABEL_TASK_AUDIT.md \
  LAYER_CAPABILITY_SUMMARY.md \
  ML_PIPELINE_DEPLOYMENT.md \
  ML_PIPELINE_IMPLEMENTATION_SUMMARY.md \
  QUICK_START_AWS.md \
  QUICK_START_DEPLOYMENT.md \
  RELEASE_READINESS_CHECKLIST.md \
  RUNBOOK_AWS.md \
  SAGEMAKER_DEPLOYMENT_CHECKLIST.md \
  SAGEMAKER_FEATURES_IMPLEMENTATION.md \
  SAGEMAKER_IMPLEMENTATION_SUMMARY.md \
  SAGEMAKER_INTEGRATION_STATUS.md \
  SAGEMAKER_LOGGING.md \
  SAGEMAKER_QUICK_REFERENCE.md \
  STACKER_5FOLD_CV.md \
  VSCODE_MCP_SETUP.md \
  VSCODE_WORKFLOW.md \
  DATA_QUALITY_GUARDS.md
```

---

- [ ] **Step 2: Update `README.md` to reflect v2 pipeline**

Find the pipeline section in `README.md` and update:
- Change `make train` description from "Train LightGBM + IsolationForest" to "Train CatBoost + LightGBM stacker (v2 features)"
- Remove any mention of `make evaluate` or `make score-v2`
- Update setup instructions to include `pip install -e bitoguard_core/`

---

- [ ] **Step 3: Update `CLAUDE.md` to reflect v2 pipeline**

In the Pipeline section:
```markdown
### Pipeline (run in order after first setup)
make sync            # Sync BitoPro data → raw.* tables in DuckDB
make features        # Build graph + tabular feature snapshots
make features-v2     # Build v2 feature snapshots (required for stacker)
make train           # Train CatBoost + LightGBM stacker (v2 features)
make score           # Score users → generate alerts (v2 stacker path)
make drift           # Feature drift detection between latest snapshots
```

In the Module table, update M3 row:
```
M3: Supervised | CatBoost + LightGBM stacker, 5-fold OOF, AUC 0.9495 | models/stacker.py, models/score.py
```

Remove `make evaluate` from the commands section (deleted target).

---

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: aggressive cleanup — keep 8 essential docs, delete 27 overlapping

Docs reduced from 35 to 8: keep GRAPH_TRUST_BOUNDARY, GRAPH_RECOVERY_PLAN,
ML_PIPELINE_SUMMARY, SAGEMAKER_DEPLOYMENT_GUIDE, RULEBOOK, MODEL_CARD,
DATA_CONTRACT, RUNBOOK_LOCAL. Update README and CLAUDE.md for v2 pipeline."
```

---

### Task 6: Test Coverage — Alert Guard + M4 Schema Guard

**Context:** Two new tests: (1) an integration test that verifies `make score` produces non-zero alerts (guards against threshold regression), and (2) a unit test that fails loudly if an IsolationForest model has a schema mismatch with v2 features.

**Files:**
- Modify: `bitoguard_core/tests/test_smoke.py`
- Modify: `bitoguard_core/tests/test_model_pipeline.py`

---

- [ ] **Step 1: Add M4 schema guard test to `bitoguard_core/tests/test_model_pipeline.py`**

Add this test at the end of the file:

```python
def test_iforest_schema_guard_if_model_exists() -> None:
    """If an IsolationForest model artifact exists, its encoded_columns metadata
    must be non-empty. A missing or empty list means the model was saved without
    schema info and would silently zero all anomaly scores at scoring time."""
    import json
    from models.common import model_dir
    iforest_metas = sorted(model_dir().glob("iforest_*.json"))
    if not iforest_metas:
        pytest.skip("No IsolationForest model found — skip schema check")
    meta = json.loads(iforest_metas[-1].read_text())
    encoded_cols = meta.get("encoded_columns", [])
    assert len(encoded_cols) > 0, (
        f"IsolationForest metadata at {iforest_metas[-1]} is missing 'encoded_columns'. "
        "Retrain with negatives-only data on v2 features before enabling m4_enabled=True."
    )
```

---

- [ ] **Step 2: Run the new test to verify it passes (or skips gracefully)**

```bash
cd bitoguard_core && source .venv/bin/activate && \
  python -m pytest tests/test_model_pipeline.py::test_iforest_schema_guard_if_model_exists -v
```
Expected: PASSED or SKIPPED (if no iforest model exists).

---

- [ ] **Step 3: Add integration alert guard to `bitoguard_core/tests/test_smoke.py`**

Append at the end of the file:

```python
@pytest.mark.integration
def test_alerts_generated_after_scoring() -> None:
    """Guards against threshold miscalibration causing zero alerts.

    This is an INTEGRATION test — it reads from the live bitoguard.duckdb.
    Run manually after `make score` with real data:

        pytest tests/test_smoke.py::test_alerts_generated_after_scoring -m integration -v

    Not included in the default `make test` suite (excluded via addopts in pyproject.toml).
    """
    from config import load_settings
    from db.store import DuckDBStore

    settings = load_settings()
    # DuckDBStore takes only db_path — no read_only kwarg; query is non-mutating.
    store = DuckDBStore(settings.db_path)
    df = store.fetch_df(
        "SELECT COUNT(*) AS cnt FROM ops.alerts WHERE risk_level IN ('medium', 'high', 'critical')"
    )
    count = int(df["cnt"].iloc[0]) if not df.empty else 0
    assert count > 0, (
        "Zero non-low alerts in ops.alerts. "
        "Check: (1) m1_enabled=True and m3_enabled=True in config.py defaults, "
        "(2) alert bins=[-1,20,50,70,100] in score.py score_latest_snapshot(). "
        "Run `make score` with real data first."
    )
```

---

- [ ] **Step 4: Verify the integration test is excluded from default test run**

```bash
cd bitoguard_core && source .venv/bin/activate && python -m pytest tests/ -q
```
Expected: `test_alerts_generated_after_scoring` does NOT run (not marked or collected without `-m integration`). All other tests pass.

---

- [ ] **Step 5: Commit**

```bash
git add bitoguard_core/tests/test_model_pipeline.py bitoguard_core/tests/test_smoke.py
git commit -m "test: add M4 schema guard and alert integration guard

test_iforest_schema_guard: fails loudly if IsolationForest model
lacks encoded_columns metadata (prevents silent zero-scoring).
test_alerts_generated_after_scoring: integration test (pytest.mark.integration)
verifying make score produces non-zero alerts — not in default make test."
```

---

## Final Verification

After all 6 tasks are complete:

- [ ] **Run full test suite**
```bash
cd bitoguard_core && source .venv/bin/activate && python -m pytest tests/ -v
```
Expected: ~83 tests pass (85 minus 2 deleted v1 tests).

- [ ] **Verify Makefile has no PYTHONPATH references**
```bash
grep -n "PYTHONPATH" Makefile
```
Expected: no output.

- [ ] **Verify no v1 imports remain**
```bash
grep -rn "from models.train import\|from models.validate import\|score_latest_snapshot_v2" bitoguard_core/ --include="*.py"
```
Expected: no output.

- [ ] **Verify docs count**
```bash
ls docs/*.md | wc -l
```
Expected: 8

- [ ] **Verify scripts count**
```bash
ls scripts/*.sh | wc -l
```
Expected: ~10 or fewer
