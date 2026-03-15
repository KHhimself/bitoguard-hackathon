# AWS SageMaker + Amplify Deployment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Team mode strict is active.** Only `executor-codex` may write files. All other agents produce diffs only.

**Goal:** Fix 8 code/infra gaps and add 2 new resources so BitoGuard deploys end-to-end on AWS with SageMaker training + Amplify frontend.

**Architecture:** Python application fixes wire the SageMaker data pipeline (import, S3 export, training data bridge, pipeline trigger endpoint). Terraform fixes align EFS mounts, repair the Step Functions flow, and add Amplify hosting. A bootstrap script seeds EFS with pre-existing DuckDB data.

**Tech Stack:** Python 3.13, FastAPI, pytest, boto3, Terraform ≥1.0, AWS (ECS Fargate, SageMaker, Step Functions, EFS, Amplify, Lambda, S3)

**Spec:** `docs/superpowers/specs/2026-03-15-aws-sagemaker-deployment-design.md`

**AWS Docs:** All implementation steps include the relevant AWS reference link. Consult before coding.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `bitoguard_core/ml_pipeline/train_entrypoint.py` | F1: fix import alias; F4: add `--use_s3_data` flag |
| Modify | `bitoguard_core/features/build_features_v2.py` | F3: read `EXPORT_TO_S3` env var, pass to registry |
| Modify | `bitoguard_core/api/main.py` | F5: add `POST /pipeline/run` endpoint |
| Modify | `infra/aws/terraform/ecs_ml_tasks.tf` | F2: align EFS access point + containerPath + env vars |
| Modify | `infra/aws/terraform/step_functions.tf` | F6: HPO→TrainStacker flow; F7: RegisterModel state; F8: States.Format |
| Modify | `infra/aws/terraform/variables.tf` | Add `github_repo_url` variable for Amplify |
| Create | `infra/aws/terraform/amplify.tf` | A1: Amplify app + branch + env vars |
| Create | `scripts/bootstrap-efs.sh` | A2: export DuckDB to S3, run copy-seed ECS task |
| Create | `bitoguard_core/tests/test_train_entrypoint.py` | Tests for F1 + F4 |
| Create | `bitoguard_core/tests/test_pipeline_api.py` | Tests for F5 |

---

## Chunk 1: Python Application Fixes (F1, F3, F4, F5)

### Task 1: Fix broken import in train_entrypoint.py (F1)

**Ref:** No AWS doc needed — pure Python fix.

**Files:**
- Modify: `bitoguard_core/ml_pipeline/train_entrypoint.py:20`
- Create: `bitoguard_core/tests/test_train_entrypoint.py`

- [ ] **Step 1.1: Write the failing test**

Create `bitoguard_core/tests/test_train_entrypoint.py`:

```python
"""Tests for ml_pipeline/train_entrypoint.py"""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_train_entrypoint_imports_without_error():
    """F1: train_entrypoint must import cleanly (no ImportError on train_catboost)."""
    import importlib
    try:
        mod = importlib.import_module("ml_pipeline.train_entrypoint")
        assert mod is not None
    except ImportError as e:
        raise AssertionError(f"train_entrypoint import failed: {e}") from e


def test_parse_args_model_type():
    """parse_args accepts all four model types."""
    from ml_pipeline.train_entrypoint import parse_args
    for model in ["lgbm", "catboost", "iforest", "stacker"]:
        args = parse_args(["--model_type", model])
        assert args.model_type == model
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
cd bitoguard_core && source .venv/bin/activate
PYTHONPATH=. pytest tests/test_train_entrypoint.py::test_train_entrypoint_imports_without_error -v
```
Expected: FAIL — `ImportError: cannot import name 'train_catboost'`

- [ ] **Step 1.3: Fix the import and parse_args signature**

Two changes in `bitoguard_core/ml_pipeline/train_entrypoint.py`:

**a) Line 20 — fix the import alias:**
```python
# Before
from models.train_catboost import train_catboost
# After
from models.train_catboost import train_catboost_model as train_catboost
```
The existing call at line ~190 (`result = train_catboost()`) works correctly via the alias.

**b) Line 91 — make parse_args() accept an optional args list** (required for tests):
```python
# Before
def parse_args():
    ...
    return parser.parse_args()

# After
def parse_args(args=None):
    ...
    return parser.parse_args(args)
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
PYTHONPATH=. pytest tests/test_train_entrypoint.py -v
```
Expected: 2 PASSED

- [ ] **Step 1.5: Commit**

```bash
git add bitoguard_core/ml_pipeline/train_entrypoint.py bitoguard_core/tests/test_train_entrypoint.py
git commit -m "fix: correct train_catboost import alias in train_entrypoint (F1)"
```

---

### Task 2: Wire EXPORT_TO_S3 flag in build_features_v2.py (F3)

**Ref:** No AWS doc needed — Python fix.

**Files:**
- Modify: `bitoguard_core/features/build_features_v2.py`
- Create: `bitoguard_core/tests/test_feature_export_flag.py`

- [ ] **Step 2.1: Write the failing test**

Create `bitoguard_core/tests/test_feature_export_flag.py`:

```python
"""Tests for build_features_v2 EXPORT_TO_S3 env var wiring (F3)."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _empty_df():
    return pd.DataFrame({"user_id": []})


def _run_build_v2(export_env: str):
    """Helper: run build_v2() with mocked dependencies."""
    empty = _empty_df()
    with patch("features.build_features_v2.load_settings") as mock_settings, \
         patch("features.build_features_v2.DuckDBStore") as mock_store_cls, \
         patch("features.build_features_v2.build_and_store_v2_features") as mock_build:
        mock_settings.return_value.db_path = "/tmp/fake.duckdb"
        mock_store = MagicMock()
        mock_store.read_table.return_value = empty
        mock_store_cls.return_value = mock_store
        mock_build.return_value = empty

        import os
        old = os.environ.get("EXPORT_TO_S3")
        try:
            if export_env:
                os.environ["EXPORT_TO_S3"] = export_env
            elif "EXPORT_TO_S3" in os.environ:
                del os.environ["EXPORT_TO_S3"]
            from features import build_features_v2
            import importlib
            importlib.reload(build_features_v2)
            build_features_v2.build_v2()
        finally:
            if old is None:
                os.environ.pop("EXPORT_TO_S3", None)
            else:
                os.environ["EXPORT_TO_S3"] = old

        return mock_build.call_args


def test_export_to_s3_true_when_env_set():
    """F3: export_to_s3=True is passed when EXPORT_TO_S3=true."""
    call = _run_build_v2("true")
    kwargs = call[1] if call else {}
    assert kwargs.get("export_to_s3") is True, f"expected export_to_s3=True, got {kwargs}"


def test_export_to_s3_false_when_env_unset():
    """F3: export_to_s3=False when EXPORT_TO_S3 is unset."""
    call = _run_build_v2("")
    kwargs = call[1] if call else {}
    assert kwargs.get("export_to_s3") is False, f"expected export_to_s3=False, got {kwargs}"
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_feature_export_flag.py::test_export_to_s3_true_when_env_set -v
```
Expected: FAIL — `export_to_s3` not in call kwargs (default False)

- [ ] **Step 2.3: Fix build_features_v2.py**

Replace the entire `build_v2()` function in `bitoguard_core/features/build_features_v2.py`:

```python
"""CLI entry-point: loads canonical tables, runs registry, stores v2 features."""
from __future__ import annotations
import os
from config import load_settings
from db.store import DuckDBStore
from features.registry import build_and_store_v2_features


def build_v2() -> None:
    settings = load_settings()
    store    = DuckDBStore(settings.db_path)
    export   = os.environ.get("EXPORT_TO_S3", "").lower() == "true"

    users   = store.read_table("canonical.users")
    fiat    = store.read_table("canonical.fiat_transactions")
    crypto  = store.read_table("canonical.crypto_transactions")
    trades  = store.read_table("canonical.trade_orders")
    logins  = store.read_table("canonical.login_events")
    edges   = store.read_table("canonical.entity_edges")

    result = build_and_store_v2_features(
        users, fiat, crypto, trades, logins, edges,
        store=store, export_to_s3=export,
    )
    print(f"[features-v2] {len(result)} users, {len(result.columns)} columns")


if __name__ == "__main__":
    build_v2()
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
PYTHONPATH=. pytest tests/test_feature_export_flag.py -v
```
Expected: 2 PASSED

- [ ] **Step 2.5: Commit**

```bash
git add bitoguard_core/features/build_features_v2.py bitoguard_core/tests/test_feature_export_flag.py
git commit -m "fix: wire EXPORT_TO_S3 env var through to build_and_store_v2_features (F3)"
```

---

### Task 3: Add --use_s3_data to train_entrypoint.py (F4)

**Ref:** https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms-training-algo-running-container.html

SageMaker mounts training data at `/opt/ml/input/data/<channel_name>`. When `--use_s3_data` is set, load Parquet from this path instead of calling DuckDB-dependent `training_dataset()`.

**Files:**
- Modify: `bitoguard_core/ml_pipeline/train_entrypoint.py`
- Modify: `bitoguard_core/tests/test_train_entrypoint.py` (add tests)

- [ ] **Step 3.1: Write failing tests — append to test_train_entrypoint.py**

```python
def test_parse_args_use_s3_data_flag():
    """F4: --use_s3_data flag is parsed correctly."""
    from ml_pipeline.train_entrypoint import parse_args

    args_with = parse_args(["--model_type", "lgbm", "--use_s3_data"])
    assert args_with.use_s3_data is True

    args_without = parse_args(["--model_type", "lgbm"])
    assert args_without.use_s3_data is False


def test_load_training_data_from_s3_path(tmp_path):
    """F4: load_training_data_from_path loads Parquet from the given directory."""
    import pandas as pd
    from ml_pipeline.train_entrypoint import load_training_data_from_path

    df = pd.DataFrame({"user_id": ["u1", "u2"], "feat_a": [1.0, 2.0],
                       "hidden_suspicious_label": [0, 1]})
    parquet_path = tmp_path / "data.parquet"
    df.to_parquet(parquet_path, index=False)

    result = load_training_data_from_path(str(tmp_path))
    assert len(result) == 2
    assert "user_id" in result.columns
    assert "hidden_suspicious_label" in result.columns
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
PYTHONPATH=. pytest tests/test_train_entrypoint.py::test_parse_args_use_s3_data_flag tests/test_train_entrypoint.py::test_load_training_data_from_s3_path -v
```
Expected: FAIL — `use_s3_data` not in namespace, `load_training_data_from_path` not found

- [ ] **Step 3.3: Implement the changes in train_entrypoint.py**

In `parse_args()`, add after the existing `--model_dir` argument:
```python
parser.add_argument(
    '--use_s3_data',
    action='store_true',
    default=False,
    help='Load training data from S3 input path instead of DuckDB'
)
```

Add this new function anywhere before `main()`:
```python
def load_training_data_from_path(input_data_path: str) -> 'pd.DataFrame':
    """Load training DataFrame from Parquet files at the given directory.

    SageMaker places channel data at /opt/ml/input/data/<channel>.
    Ref: https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms-training-algo-running-container.html
    """
    import glob
    import pandas as pd

    parquet_files = glob.glob(f"{input_data_path}/**/*.parquet", recursive=True)
    if not parquet_files:
        parquet_files = glob.glob(f"{input_data_path}/*.parquet")
    if not parquet_files:
        raise FileNotFoundError(f"No Parquet files found in {input_data_path}")
    return pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
```

In `main()`, after `args = parse_args()`, add the data loading branch. Wherever training functions are called that need the dataset, pass it in if `args.use_s3_data` is set:
```python
training_df = None
if args.use_s3_data:
    training_df = load_training_data_from_path(args.input_data)
    logger.info(f"Loaded {len(training_df)} rows from S3 input: {args.input_data}")
```
Then thread `training_df` into the model-type dispatch block so each branch calls `train_model(df=training_df)` etc. when `training_df is not None`, otherwise falls back to the existing DuckDB path.

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
PYTHONPATH=. pytest tests/test_train_entrypoint.py -v
```
Expected: 4 PASSED

- [ ] **Step 3.5: Commit**

```bash
git add bitoguard_core/ml_pipeline/train_entrypoint.py bitoguard_core/tests/test_train_entrypoint.py
git commit -m "feat: add --use_s3_data flag to train_entrypoint for SageMaker (F4)"
```

---

### Task 4: Add POST /pipeline/run endpoint (F5)

**Ref:** https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-api-gateway.html
**Ref:** https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/stepfunctions.html

**Files:**
- Modify: `bitoguard_core/api/main.py`
- Create: `bitoguard_core/tests/test_pipeline_api.py`

- [ ] **Step 4.1: Write the failing test**

Create `bitoguard_core/tests/test_pipeline_api.py`:

```python
"""Tests for POST /pipeline/run endpoint (F5)."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

FAKE_ARN = "arn:aws:states:us-west-2:123456789012:stateMachine:bitoguard-prod-ml-pipeline"
FAKE_EXEC_ARN = "arn:aws:states:us-west-2:123456789012:execution:bitoguard-prod-ml-pipeline:test-run"


def _mock_sfn():
    mock = MagicMock()
    mock.start_execution.return_value = {"executionArn": FAKE_EXEC_ARN}
    return mock


def test_pipeline_run_returns_execution_arn(monkeypatch):
    """F5: POST /pipeline/run returns execution_arn from Step Functions."""
    monkeypatch.setenv("BITOGUARD_STEP_FUNCTIONS_ARN", FAKE_ARN)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    with patch("boto3.client", return_value=_mock_sfn()):
        resp = client.post("/pipeline/run", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert "execution_arn" in body
    assert body["execution_arn"] == FAKE_EXEC_ARN


def test_pipeline_run_passes_enable_tuning_false_by_default(monkeypatch):
    """F5: enable_tuning defaults to False in Step Functions input."""
    monkeypatch.setenv("BITOGUARD_STEP_FUNCTIONS_ARN", FAKE_ARN)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    mock_sfn = _mock_sfn()
    with patch("boto3.client", return_value=mock_sfn):
        client.post("/pipeline/run", json={})

    call_kwargs = mock_sfn.start_execution.call_args[1]
    payload = json.loads(call_kwargs["input"])
    assert payload["enable_tuning"] is False


def test_pipeline_run_passes_enable_tuning_true(monkeypatch):
    """F5: enable_tuning=True is forwarded to Step Functions."""
    monkeypatch.setenv("BITOGUARD_STEP_FUNCTIONS_ARN", FAKE_ARN)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    mock_sfn = _mock_sfn()
    with patch("boto3.client", return_value=mock_sfn):
        client.post("/pipeline/run", json={"enable_tuning": True})

    call_kwargs = mock_sfn.start_execution.call_args[1]
    payload = json.loads(call_kwargs["input"])
    assert payload["enable_tuning"] is True


def test_pipeline_run_missing_arn_env_returns_500(monkeypatch):
    """F5: returns 500 if BITOGUARD_STEP_FUNCTIONS_ARN is not set."""
    monkeypatch.delenv("BITOGUARD_STEP_FUNCTIONS_ARN", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    resp = client.post("/pipeline/run", json={})
    assert resp.status_code == 500
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_pipeline_api.py::test_pipeline_run_returns_execution_arn -v
```
Expected: FAIL — 404 (route does not exist)

- [ ] **Step 4.3: Add the endpoint to api/main.py**

Find the imports section at the top of `bitoguard_core/api/main.py` and ensure these are present (add if missing):
```python
import json
import os
import time
```

Find a logical location (e.g., after the existing `/pipeline/sync` endpoint) and add:

```python
from pydantic import BaseModel

class PipelineRunRequest(BaseModel):
    enable_tuning: bool = False

@app.post("/pipeline/run")
async def run_pipeline(request: PipelineRunRequest = PipelineRunRequest()):
    """Trigger the Step Functions ML pipeline.

    Body:
        enable_tuning: If True, runs full hyperparameter tuning (2-3h).
                       If False, uses best params from SSM (15-25 min).

    Ref: https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-api-gateway.html
    """
    arn = os.environ.get("BITOGUARD_STEP_FUNCTIONS_ARN")
    if not arn:
        raise HTTPException(
            status_code=500,
            detail="BITOGUARD_STEP_FUNCTIONS_ARN environment variable not set",
        )
    region = os.environ.get("AWS_REGION", "us-east-1")
    import boto3
    sfn = boto3.client("stepfunctions", region_name=region)
    execution_name = f"api-run-{int(time.time())}"
    resp = sfn.start_execution(
        stateMachineArn=arn,
        name=execution_name,
        input=json.dumps({"enable_tuning": request.enable_tuning}),
    )
    return {"execution_arn": resp["executionArn"]}
```

Also update Step 4.1 test to use `json={"enable_tuning": True}` which already matches body semantics — no test change needed since the tests already use `json=` which is correct for body parameters.

- [ ] **Step 4.4: Run all pipeline API tests**

```bash
PYTHONPATH=. pytest tests/test_pipeline_api.py -v
```
Expected: 4 PASSED

- [ ] **Step 4.5: Run full test suite to check for regressions**

```bash
PYTHONPATH=. pytest tests/ -q
```
Expected: all existing tests still pass

- [ ] **Step 4.6: Commit**

```bash
git add bitoguard_core/api/main.py bitoguard_core/tests/test_pipeline_api.py
git commit -m "feat: add POST /pipeline/run endpoint to trigger Step Functions (F5)"
```

---

## Chunk 2: Terraform Infrastructure Fixes (F2, F6, F7, F8)

> **Note:** These are HCL/Terraform changes. Verification is `terraform validate` + `terraform plan`. All changes are in `infra/aws/terraform/`.

### Task 5: Fix EFS mount alignment in ecs_ml_tasks.tf (F2)

**Ref:** https://docs.aws.amazon.com/AmazonECS/latest/developerguide/efs-volumes.html

**Files:**
- Modify: `infra/aws/terraform/ecs_ml_tasks.tf`

- [ ] **Step 5.1: Read the current task definitions**

Read `infra/aws/terraform/ecs_ml_tasks.tf` to locate the three task definitions: `ml_sync`, `ml_features`, `ml_scoring`. Note the current `accessPointId` and `containerPath` values.

- [ ] **Step 5.2: Fix all three task definitions**

For each of the three ECS task definitions (`aws_ecs_task_definition.ml_sync`, `aws_ecs_task_definition.ml_features`, `aws_ecs_task_definition.ml_scoring`):

**a) In the `volume` block**, change:
```hcl
# Before
access_point_id = aws_efs_access_point.ml_pipeline.id
# After
access_point_id = aws_efs_access_point.artifacts.id
```

**b) In the `container_definitions` JSON**, change `containerPath`:
```json
// Before
"containerPath": "/opt/ml/artifacts"
// After
"containerPath": "/mnt/efs/artifacts"
```

**c) In each task's `environment` array**, add (or update if present):
```json
{"name": "BITOGUARD_DB_PATH", "value": "/mnt/efs/artifacts/bitoguard.duckdb"},
{"name": "BITOGUARD_ARTIFACT_DIR", "value": "/mnt/efs/artifacts"}
```

- [ ] **Step 5.3: Validate**

```bash
cd infra/aws/terraform
terraform validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 5.4: Check plan for EFS changes**

```bash
terraform plan -target=aws_ecs_task_definition.ml_sync \
               -target=aws_ecs_task_definition.ml_features \
               -target=aws_ecs_task_definition.ml_scoring
```
Expected: 3 resources to update (EFS access point and container path changes visible)

- [ ] **Step 5.5: Commit**

```bash
cd ../../..
git add infra/aws/terraform/ecs_ml_tasks.tf
git commit -m "fix: align EFS access point and containerPath across all ML ECS tasks (F2)

All ML pipeline tasks now use aws_efs_access_point.artifacts (root /artifacts)
mounted at /mnt/efs/artifacts, matching the backend task. Sets BITOGUARD_DB_PATH
and BITOGUARD_ARTIFACT_DIR env vars so pipeline scripts find DuckDB correctly.
Ref: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/efs-volumes.html"
```

---

### Task 6: Fix Step Functions flow and add missing states (F6, F7, F8)

**Ref:** https://docs.aws.amazon.com/step-functions/latest/dg/concepts-amazon-states-language.html
**Ref:** https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-intrinsic-functions.html
**Ref:** https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html

**Files:**
- Modify: `infra/aws/terraform/step_functions.tf`

This task has three sub-fixes applied to the ASL JSON string embedded in the Terraform HCL.

**Sub-fix F6: Route HyperparameterTuning → AnalyzeTuning → TrainStacker**

- [ ] **Step 6.1: Fix HyperparameterTuning.Next**

In `step_functions.tf`, find the `HyperparameterTuning` state (around line 492). Change:
```json
// Before (in the HyperparameterTuning state)
"Next": "ScoringStage"
// After
"Next": "AnalyzeTuning"
```

- [ ] **Step 6.2: Add AnalyzeTuning state**

After the closing brace of `HyperparameterTuning` (around line 500) and before the `ParallelTraining` state (around line 502) — note that `ParallelTraining` exists between `HyperparameterTuning` and `TrainStacker` in the file — insert the `AnalyzeTuning` state:
```json
"AnalyzeTuning": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {
    "FunctionName": "${aws_lambda_function.tuning_analyzer.arn}",
    "Payload": {
      "execution_id.$": "$$.Execution.Name",
      "tuning_results.$": "$.tuning_results"
    }
  },
  "ResultPath": "$.tuning_analysis",
  "Retry": [{"ErrorEquals": ["Lambda.ServiceException"], "IntervalSeconds": 5, "MaxAttempts": 2}],
  "Next": "TrainStacker"
},
```

**Sub-fix F7: Route TrainStacker → RegisterModel → ScoringStage**

- [ ] **Step 6.3: Fix TrainStacker.Next**

Find the `TrainStacker` state (around line 692). Change:
```json
// Before
"Next": "ScoringStage"
// After
"Next": "RegisterModel"
```

- [ ] **Step 6.4: Add RegisterModel state**

After `TrainStacker` and before `ScoringStage`, insert:
```json
"RegisterModel": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {
    "FunctionName": "${aws_lambda_function.model_registry.arn}",
    "Payload": {
      "execution_id.$": "$$.Execution.Name",
      "model_artifacts.$": "$.stacker_artifacts",
      "model_type": "stacker"
    }
  },
  "ResultPath": "$.registration",
  "Retry": [{"ErrorEquals": ["Lambda.ServiceException"], "IntervalSeconds": 5, "MaxAttempts": 2}],
  "Next": "ScoringStage"
},
```

**Sub-fix F8: Fix States.Format for dynamic SageMaker job names**

- [ ] **Step 6.5: Fix all dynamic job name interpolations with States.Format**

The following 8 locations in `step_functions.tf` use broken string interpolation for SageMaker job names. Apply `States.Format` to each. Note: fields that use `.$` suffix enable JSONPath/intrinsic evaluation — add the `.$` suffix when changing from a plain string key.

**Ref:** https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-intrinsic-functions.html

| Approx Line | Field | Before | After |
|-------------|-------|--------|-------|
| ~141 | `ProcessingJobName` | `"bitoguard-preprocessing-$.Execution.Name"` | `"ProcessingJobName.$": "States.Format('bitoguard-preprocessing-{}', $$.Execution.Name)"` |
| ~191 | `SNAPSHOT_ID` (env var) | `"$.Execution.Name"` | `"SNAPSHOT_ID.$": "States.Format('{}', $$.Execution.Name)"` |
| ~247 | `HyperParameterTuningJobName` (lgbm) | `"bitoguard-lgbm-tuning-$.Execution.Name"` | `"HyperParameterTuningJobName.$": "States.Format('bitoguard-lgbm-tuning-{}', $$.Execution.Name)"` |
| ~381 | `HyperParameterTuningJobName` (catboost) | `"bitoguard-catboost-tuning-$.Execution.Name"` | `"HyperParameterTuningJobName.$": "States.Format('bitoguard-catboost-tuning-{}', $$.Execution.Name)"` |
| ~512 | `TrainingJobName` (lgbm) | `"bitoguard-lgbm-$$.Execution.Name"` | `"TrainingJobName.$": "States.Format('bitoguard-lgbm-{}', $$.Execution.Name)"` |
| ~556 | `TrainingJobName` (catboost) | `"bitoguard-catboost-$$.Execution.Name"` | `"TrainingJobName.$": "States.Format('bitoguard-catboost-{}', $$.Execution.Name)"` |
| ~602 | `TrainingJobName` (iforest) | `"bitoguard-iforest-$$.Execution.Name"` | `"TrainingJobName.$": "States.Format('bitoguard-iforest-{}', $$.Execution.Name)"` |
| ~656 | `TrainingJobName` (stacker) | `"bitoguard-stacker-$.Execution.Name"` | `"TrainingJobName.$": "States.Format('bitoguard-stacker-{}', $$.Execution.Name)"` |

Pattern to apply for each:
1. Remove the old key (e.g., `"ProcessingJobName"`)
2. Add the new key with `.$` suffix and `States.Format(...)` value
3. Use `$$.Execution.Name` (double-dollar) as the JSONPath context reference — this is the correct way to reference the execution context in Step Functions ASL

- [ ] **Step 6.6: Validate Terraform**

```bash
cd infra/aws/terraform
terraform validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 6.7: Plan to verify state machine changes**

```bash
terraform plan -target=aws_sfn_state_machine.ml_pipeline
```
Expected: 1 resource to update (state machine definition changes visible in diff)

- [ ] **Step 6.8: Commit**

```bash
cd ../../..
git add infra/aws/terraform/step_functions.tf
git commit -m "fix: repair Step Functions flow and States.Format intrinsics (F6, F7, F8)

F6: HyperparameterTuning now routes to AnalyzeTuning (Lambda) then TrainStacker
F7: TrainStacker now routes to RegisterModel (Lambda) before ScoringStage
F8: All SageMaker job names use States.Format intrinsic instead of literal strings
Ref: https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-intrinsic-functions.html"
```

---

## Chunk 3: New Resources (A1 Amplify, A2 Bootstrap)

### Task 7: Add Amplify Terraform resource (A1)

**Ref:** https://docs.aws.amazon.com/amplify/latest/userguide/server-side-rendering-amplify.html
**Ref:** https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/amplify_app

**Files:**
- Create: `infra/aws/terraform/amplify.tf`
- Modify: `infra/aws/terraform/variables.tf`

- [ ] **Step 7.1: Add github_repo_url variable**

In `infra/aws/terraform/variables.tf`, append:
```hcl
variable "github_repo_url" {
  description = "GitHub repository URL for Amplify (e.g. https://github.com/org/repo)"
  type        = string
  default     = ""
}

variable "github_access_token" {
  description = "GitHub personal access token for Amplify repo connection"
  type        = string
  sensitive   = true
  default     = ""
}
```

- [ ] **Step 7.2: Create amplify.tf**

Create `infra/aws/terraform/amplify.tf`:

```hcl
# AWS Amplify Frontend (Next.js SSR)
# Ref: https://docs.aws.amazon.com/amplify/latest/userguide/server-side-rendering-amplify.html
# Ref: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/amplify_app

resource "aws_amplify_app" "frontend" {
  name         = "${local.name_prefix}-frontend"
  repository   = var.github_repo_url
  access_token = var.github_access_token

  # WEB_COMPUTE required for Next.js SSR and API routes
  platform = "WEB_COMPUTE"

  build_spec = <<-EOT
    version: 1
    frontend:
      phases:
        preBuild:
          commands:
            - cd bitoguard_frontend
            - npm ci
        build:
          commands:
            - npm run build
      artifacts:
        baseDirectory: bitoguard_frontend/.next
        files:
          - '**/*'
      cache:
        paths:
          - bitoguard_frontend/node_modules/**/*
  EOT

  # Redirect all routes to Next.js for SPA/SSR handling
  custom_rule {
    source = "/<*>"
    status = "404-200"
    target = "/index.html"
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-frontend"
  })
}

resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.frontend.id
  branch_name = "main"
  framework   = "Next.js - SSR"
  stage       = "PRODUCTION"

  environment_variables = {
    # Backend API base — proxied through Next.js API routes
    # Set to the internal ALB DNS (not public) since Amplify SSR runs server-side
    BITOGUARD_INTERNAL_API_BASE = "http://${aws_lb.main.dns_name}"
    NODE_ENV                    = "production"
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-frontend-main"
  })
}

output "amplify_app_url" {
  description = "Amplify app default domain"
  value       = "https://main.${aws_amplify_app.frontend.default_domain}"
}

output "amplify_app_id" {
  description = "Amplify app ID (for manual deploys)"
  value       = aws_amplify_app.frontend.id
}
```

- [ ] **Step 7.3: Add github_repo_url to terraform.tfvars.example**

In `infra/aws/terraform/terraform.tfvars.example`, append:
```hcl
github_repo_url     = "https://github.com/YOUR_ORG/bitoguard-hackathon"
github_access_token = "ghp_YOUR_TOKEN_HERE"
```

- [ ] **Step 7.4: Validate**

```bash
cd infra/aws/terraform
terraform validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 7.5: Plan Amplify resources**

```bash
terraform plan -target=aws_amplify_app.frontend -target=aws_amplify_branch.main
```
Expected: 2 resources to add

- [ ] **Step 7.6: Commit**

```bash
cd ../../..
git add infra/aws/terraform/amplify.tf infra/aws/terraform/variables.tf infra/aws/terraform/terraform.tfvars.example
git commit -m "feat: add Amplify WEB_COMPUTE resource for Next.js SSR frontend (A1)

Adds aws_amplify_app (WEB_COMPUTE platform) and aws_amplify_branch (main).
Build spec handles Next.js App Router SSR. BITOGUARD_INTERNAL_API_BASE
points to ALB DNS for server-side fetch calls.
Ref: https://docs.aws.amazon.com/amplify/latest/userguide/server-side-rendering-amplify.html"
```

---

### Task 8: Add EFS bootstrap script (A2)

**Ref:** https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html
**Ref:** https://docs.aws.amazon.com/cli/latest/reference/s3/cp.html

**Files:**
- Create: `scripts/bootstrap-efs.sh`
- Modify: `infra/aws/terraform/ecs_ml_tasks.tf` (add copy-seed task definition)

- [ ] **Step 8.1: Add copy-seed ECS task definition**

In `infra/aws/terraform/ecs_ml_tasks.tf`, add a one-shot ECS task that copies DuckDB from S3 to EFS if EFS is empty:

```hcl
resource "aws_ecs_task_definition" "copy_seed" {
  family                   = "${local.name_prefix}-copy-seed"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn

  container_definitions = jsonencode([{
    name      = "copy-seed"
    image     = "${aws_ecr_repository.backend.repository_url}:latest"
    essential = true
    command   = [
      "sh", "-c",
      "if [ ! -f /mnt/efs/artifacts/bitoguard.duckdb ]; then mkdir -p /mnt/efs/artifacts && aws s3 cp s3://${aws_s3_bucket.artifacts.bucket}/seed/bitoguard.duckdb /mnt/efs/artifacts/bitoguard.duckdb && echo 'Seed complete'; else echo 'EFS already seeded, skipping'; fi"
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/${local.name_prefix}/copy-seed"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
    mountPoints = [{
      sourceVolume  = "efs-artifacts"
      containerPath = "/mnt/efs/artifacts"
      readOnly      = false
    }]
  }])

  volume {
    name = "efs-artifacts"
    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.bitoguard.id
      access_point_id         = aws_efs_access_point.artifacts.id
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.artifacts.id
        iam             = "ENABLED"
      }
    }
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-copy-seed" })
}

resource "aws_cloudwatch_log_group" "copy_seed" {
  name              = "/ecs/${local.name_prefix}/copy-seed"
  retention_in_days = 7
  tags              = local.common_tags
}

output "copy_seed_task_definition_arn" {
  value = aws_ecs_task_definition.copy_seed.arn
}
```

- [ ] **Step 8.1b: Add missing Terraform outputs to outputs.tf**

The bootstrap script needs 4 outputs that don't exist yet. Append to `infra/aws/terraform/outputs.tf`:

```hcl
output "artifacts_bucket_name" {
  description = "S3 artifacts bucket name"
  value       = aws_s3_bucket.artifacts.bucket
}

output "aws_region" {
  description = "AWS region"
  value       = var.aws_region
}

output "private_subnet_ids" {
  description = "Private subnet IDs for ECS tasks"
  value       = aws_subnet.private[*].id
}

output "ecs_security_group_id" {
  description = "ECS tasks security group ID"
  value       = aws_security_group.ecs_tasks.id
}
```

```bash
git add infra/aws/terraform/outputs.tf
git commit -m "fix: add missing Terraform outputs needed by bootstrap-efs.sh"
```

- [ ] **Step 8.2: Create bootstrap-efs.sh**

Create `scripts/bootstrap-efs.sh`:

```bash
#!/usr/bin/env bash
# bootstrap-efs.sh — Seed EFS with local DuckDB on first deploy
# Run once after `terraform apply` completes.
# Ref: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$PROJECT_ROOT/infra/aws/terraform"
DUCKDB_PATH="$PROJECT_ROOT/bitoguard_core/artifacts/bitoguard.duckdb"

if [ ! -f "$DUCKDB_PATH" ]; then
  echo "ERROR: $DUCKDB_PATH not found. Run 'make sync && make features' locally first."
  exit 1
fi

# Get values from Terraform outputs
BUCKET=$(terraform -chdir="$TF_DIR" output -raw artifacts_bucket_name)
CLUSTER=$(terraform -chdir="$TF_DIR" output -raw ecs_cluster_name)
TASK_DEF=$(terraform -chdir="$TF_DIR" output -raw copy_seed_task_definition_arn)
REGION=$(terraform -chdir="$TF_DIR" output -raw aws_region 2>/dev/null || echo "${AWS_REGION:-us-west-2}")
SUBNETS=$(terraform -chdir="$TF_DIR" output -json private_subnet_ids | tr -d '[]"' | tr ',' ' ')
SG=$(terraform -chdir="$TF_DIR" output -raw ecs_security_group_id)

echo "=== BitoGuard EFS Bootstrap ==="
echo "Uploading DuckDB to s3://$BUCKET/seed/bitoguard.duckdb ..."
aws s3 cp "$DUCKDB_PATH" "s3://$BUCKET/seed/bitoguard.duckdb" --region "$REGION"
echo "Upload complete."

echo "Running copy-seed ECS task ..."
TASK_ARN=$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEF" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}" \
  --region "$REGION" \
  --query 'tasks[0].taskArn' \
  --output text)

echo "Task started: $TASK_ARN"
echo "Waiting for task to complete (this may take 1-2 minutes)..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION"

EXIT_CODE=$(aws ecs describe-tasks \
  --cluster "$CLUSTER" \
  --tasks "$TASK_ARN" \
  --region "$REGION" \
  --query 'tasks[0].containers[0].exitCode' \
  --output text)

if [ "$EXIT_CODE" = "0" ]; then
  echo "EFS bootstrap complete. DuckDB is ready on EFS."
else
  echo "ERROR: copy-seed task failed with exit code $EXIT_CODE"
  echo "Check CloudWatch logs: /ecs/bitoguard-prod/copy-seed"
  exit 1
fi
```

- [ ] **Step 8.3: Make the script executable**

```bash
chmod +x scripts/bootstrap-efs.sh
```

- [ ] **Step 8.4: Validate Terraform**

```bash
cd infra/aws/terraform && terraform validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 8.5: Commit**

```bash
cd ../../../
git add scripts/bootstrap-efs.sh infra/aws/terraform/ecs_ml_tasks.tf
git commit -m "feat: add EFS bootstrap script and copy-seed ECS task (A2)

bootstrap-efs.sh uploads local DuckDB to S3 then runs a one-shot ECS Fargate
task that copies it to EFS only if EFS is empty (idempotent).
copy-seed task definition uses the backend image with an inline shell command.
Ref: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html"
```

---

## Deployment Verification

After all tasks complete, run the deployment sequence from the spec:

```bash
# 1. Init + targeted ECR apply
cd infra/aws/terraform
terraform init
terraform apply -target=aws_ecr_repository.backend -target=aws_ecr_repository.frontend

# 2. ECR login + build + push
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_REGION:-us-west-2}
ECR="$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $ECR

cd ../../..
docker build -f bitoguard_core/Dockerfile -t $ECR/bitoguard-backend:latest bitoguard_core/ && docker push $_
docker build -f bitoguard_core/Dockerfile.training -t $ECR/bitoguard-backend:training bitoguard_core/ && docker push $_
docker build -f bitoguard_core/Dockerfile.processing -t $ECR/bitoguard-backend:processing bitoguard_core/ && docker push $_

# 3. Full apply
cd infra/aws/terraform && terraform apply

# 4. Bootstrap EFS
cd ../../.. && ./scripts/bootstrap-efs.sh

# 5. Health check
ALB=$(cd infra/aws/terraform && terraform output -raw alb_url)
curl https://$ALB/healthz   # expect {"status": "ok"}

# 6. Pre-demo tuning run (night before)
SM=$(cd infra/aws/terraform && terraform output -raw ml_pipeline_state_machine_arn)
aws stepfunctions start-execution --state-machine-arn $SM \
  --name "tuning-$(date +%Y%m%d)" --input '{"enable_tuning": true}'

# 7. Demo day — trigger from UI or:
aws stepfunctions start-execution --state-machine-arn $SM \
  --name "demo-$(date +%Y%m%d-%H%M)" --input '{"enable_tuning": false}'
```
