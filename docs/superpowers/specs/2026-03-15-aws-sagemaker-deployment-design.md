# AWS SageMaker + Frontend Deployment Design
**Date:** 2026-03-15
**Project:** BitoGuard AML Detection System
**Goal:** Deploy full automated ML pipeline on SageMaker + frontend on AWS Amplify for hackathon demo

---

## 1. Overview

Deploy BitoGuard to AWS with:
- **AWS Amplify** serving the Next.js frontend (SSR + API routes, `WEB_COMPUTE` platform)
- **ECS Fargate** running the FastAPI backend (:8001) with DuckDB on EFS
- **Step Functions** orchestrating the full pipeline: sync → features → SageMaker training → model registry → scoring
- **SageMaker Hyperparameter Tuning** for pre-demo model optimization; best params stored in SSM for demo-day fast runs
- **Pre-seeded data** (local DuckDB → S3 → EFS bootstrap) with live BitoPro API as primary source

This is a hackathon demo deployment. Correctness and impressiveness take priority over cost optimization.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────┐
│                       AWS                            │
│                                                      │
│  Amplify (WEB_COMPUTE) ──► Next.js frontend (:3000) │
│                                 │                    │
│                        Next.js API routes            │
│                                 │                    │
│  ALB ──────► ECS Fargate: FastAPI backend (:8001)   │
│                    │         │                       │
│                   EFS      S3 (artifacts + features) │
│     (access point: artifacts,                        │
│      containerPath: /mnt/efs/artifacts)              │
│                                                      │
│  POST /pipeline/run  ──►  Step Functions             │
│                              │                       │
│  ┌────────────────────────────────────────────────┐  │
│  │ DataSync (ECS)                                 │  │
│  │   → FeatureEngineering (ECS → S3)              │  │
│  │   → Preprocessing (SM Processing Job)          │  │
│  │   → CheckTuningEnabled (reads $.enable_tuning) │  │
│  │       ├── true  → HyperparamTuning (SM HPO)    │  │
│  │       │            → AnalyzeTuning (Lambda)     │  │
│  │       │            → TrainStacker (SM Training) │  │
│  │       └── false → TrainStacker (SM Training)   │  │
│  │   → RegisterModel (Lambda) [NEW]               │  │
│  │   → Scoring (ECS)                              │  │
│  │   → DriftDetection → Notify                   │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  SageMaker Model Registry:                          │
│    lgbm-models, catboost-models, stacker-models     │
└─────────────────────────────────────────────────────┘
```

**Key architectural decisions:**
- All ECS tasks (backend + pipeline) share the same EFS access point (`aws_efs_access_point.artifacts`, root `/artifacts`, containerPath `/mnt/efs/artifacts`)
- SageMaker jobs read training data from S3 (no EFS access); `preprocessing_entrypoint.py` bridges DuckDB → S3 Parquet
- `CheckTuningEnabled` reads `$.enable_tuning` from Step Functions execution input (not SSM directly)
- Tuning mode is toggled by passing `{"enable_tuning": true/false}` in `start-execution --input`
- ECR has one repository (`bitoguard-backend`) with three tags: `latest` (backend), `training`, `processing`

---

## 3. Pipeline Modes

### Tuning Mode (pre-demo, run once, ~2-3 hours, ~$50-80)
```bash
aws stepfunctions start-execution \
  --state-machine-arn $(terraform -chdir=infra/aws/terraform output -raw ml_pipeline_state_machine_arn) \
  --name "pre-demo-tuning-$(date +%Y%m%d)" \
  --input '{"enable_tuning": true}'
```

Flow: `DataSync → FeatureEngineering → Preprocessing → HyperparamTuning (LightGBM + CatBoost, 20 jobs, Bayesian) → AnalyzeTuning (Lambda: writes best params to SSM) → TrainStacker → RegisterModel → Scoring → DriftDetection → Notify`

### Demo Mode (demo day, ~15-25 min)
```bash
aws stepfunctions start-execution \
  --state-machine-arn $(terraform -chdir=infra/aws/terraform output -raw ml_pipeline_state_machine_arn) \
  --name "demo-run-$(date +%Y%m%d-%H%M)" \
  --input '{"enable_tuning": false}'
```

Flow: `DataSync → FeatureEngineering → Preprocessing → [skip HPO] → TrainStacker (best params from SSM) → RegisterModel → Scoring → DriftDetection → Notify`

Also triggerable via frontend: `POST /pipeline/run` with body `{"enable_tuning": false}`.

---

## 4. Infrastructure Fixes Required

### F1 — Broken Import (BLOCKER)
**File:** `bitoguard_core/ml_pipeline/train_entrypoint.py` line 20
**Change:**
```python
# Before
from models.train_catboost import train_catboost
# After
from models.train_catboost import train_catboost_model as train_catboost
```
`train_catboost.py` exports `train_catboost_model`, not `train_catboost`. The existing call at line ~190 (`result = train_catboost()`) works correctly via the alias — no change needed there.

### F2 — EFS Mount Alignment (HIGH)
**File:** `infra/aws/terraform/ecs_ml_tasks.tf`
**Change:** In all three ML task definitions (`ml_sync`, `ml_features`, `ml_scoring`), update the EFS volume mount:
- `fileSystemId`: keep as `aws_efs_file_system.main.id`
- `accessPointId`: change from `aws_efs_access_point.ml_pipeline.id` → `aws_efs_access_point.artifacts.id`
- `containerPath`: change from `/opt/ml/artifacts` → `/mnt/efs/artifacts`

Add these environment variables to all three task container definitions:
```json
{"name": "BITOGUARD_DB_PATH", "value": "/mnt/efs/artifacts/bitoguard.duckdb"},
{"name": "BITOGUARD_ARTIFACT_DIR", "value": "/mnt/efs/artifacts"}
```

**Note:** The `artifacts` access point has root `/artifacts`, mounted at `/mnt/efs/artifacts`. The DuckDB file path is therefore `/mnt/efs/artifacts/bitoguard.duckdb`. This matches the backend's effective path.
**Ref:** https://docs.aws.amazon.com/AmazonECS/latest/developerguide/efs-volumes.html

### F3 — S3 Feature Export Flag (MEDIUM)
**File:** `bitoguard_core/features/build_features_v2.py`
**Change:** In `build_v2()`, read the `EXPORT_TO_S3` env var and pass it through:
```python
import os

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
```
`build_and_store_v2_features()` already supports `export_to_s3` in `features/registry.py`. Bug is only in the CLI entry point not passing the flag.

### F4 — SageMaker Training Data Bridge (HIGH)
**File:** `bitoguard_core/ml_pipeline/train_entrypoint.py`
**Change:** Add `--use_s3_data` flag to `parse_args()`. When set, load the training DataFrame from Parquet files at `/opt/ml/input/data/training` instead of calling internal `training_dataset()` which requires DuckDB. Pass the loaded DataFrame to the training functions.

SageMaker training jobs run on isolated EC2 instances with no EFS access. Training data must come from the S3 input channel populated by the Preprocessing step.
**Ref:** https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms-training-algo-running-container.html

### F5 — Pipeline Trigger Endpoint (MEDIUM)
**File:** `bitoguard_core/api/main.py`
**Change:** Add endpoint:
```python
@app.post("/pipeline/run")
async def run_pipeline(enable_tuning: bool = False):
    """Trigger the Step Functions ML pipeline."""
    import boto3
    sfn = boto3.client("stepfunctions", region_name=os.environ["AWS_REGION"])
    arn = os.environ["BITOGUARD_STEP_FUNCTIONS_ARN"]
    resp = sfn.start_execution(
        stateMachineArn=arn,
        name=f"api-run-{int(time.time())}",
        input=json.dumps({"enable_tuning": enable_tuning}),
    )
    return {"execution_arn": resp["executionArn"]}
```
Add `BITOGUARD_STEP_FUNCTIONS_ARN` and `AWS_REGION` env vars to the backend ECS task definition in `ecs.tf`.
**Ref:** https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-api-gateway.html

### F6 — Step Functions: HyperparamTuning Must Flow to TrainStacker (HIGH)
**File:** `infra/aws/terraform/step_functions.tf`
**Change:** In the `HyperparameterTuning` state, change `"Next": "ScoringStage"` to `"Next": "AnalyzeTuning"`. Add `AnalyzeTuning` (Lambda invoke for `tuning_analyzer`) with `"Next": "TrainStacker"`. This ensures the tuning branch feeds its best params into the stacker before scoring.

### F7 — Step Functions: Add RegisterModel State (NEW)
**File:** `infra/aws/terraform/step_functions.tf`
**Change:** After `TrainStacker` and before `ScoringStage`, add a `RegisterModel` state that invokes the `model_registry` Lambda. This registers the trained stacker artifact in the SageMaker Model Registry with `Approved` status.
**Ref:** https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html

### F8 — Step Functions: Fix Dynamic Name Interpolation (HIGH)
**File:** `infra/aws/terraform/step_functions.tf`
**Change:** All SageMaker job names using `$.Execution.Name` must use the `States.Format` intrinsic:
```json
"ProcessingJobName.$": "States.Format('bitoguard-preprocessing-{}', $$.Execution.Name)"
```
Replace bare string concatenation patterns like `"bitoguard-preprocessing-$.Execution.Name"`. Without this fix, SageMaker rejects the job name as a literal string containing `$`.
**Ref:** https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-intrinsic-functions.html

### A1 — Amplify Terraform Resource (NEW)
**File:** `infra/aws/terraform/amplify.tf` (new file)
**Key resources:**
```hcl
resource "aws_amplify_app" "frontend" {
  name       = "${local.name_prefix}-frontend"
  repository = var.github_repo_url   # add to variables.tf
  platform   = "WEB_COMPUTE"         # required for Next.js SSR

  build_spec = <<-EOT
    version: 1
    frontend:
      phases:
        preBuild:
          commands:
            - cd bitoguard_frontend && npm ci
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
}

resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.frontend.id
  branch_name = "main"
  framework   = "Next.js - SSR"
  stage       = "PRODUCTION"

  environment_variables = {
    BITOGUARD_INTERNAL_API_BASE = "http://${aws_lb.main.dns_name}"
  }
}
```
**Ref:** https://docs.aws.amazon.com/amplify/latest/userguide/server-side-rendering-amplify.html
**Ref:** https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/amplify_app

### A2 — EFS Bootstrap Script (NEW)
**File:** `scripts/bootstrap-efs.sh` (new file)
Seeds EFS with local DuckDB on first deploy. Run once after `terraform apply`:
```bash
#!/bin/bash
set -e
BUCKET=$(terraform -chdir=infra/aws/terraform output -raw artifacts_bucket_name)
aws s3 cp bitoguard_core/artifacts/bitoguard.duckdb s3://$BUCKET/seed/bitoguard.duckdb
# Run one-shot ECS task to copy from S3 → EFS
# (Task definition: copy-seed, runs aws s3 cp then exits)
```
The `copy-seed` ECS task definition is added to `ecs_ml_tasks.tf`.

---

## 5. Deployment Sequence

```bash
# Prerequisites: AWS CLI configured, Docker running, Terraform >= 1.0

# Step 1 — Initialize Terraform
cd infra/aws/terraform
terraform init    # required before any apply
cp terraform.tfvars.example terraform.tfvars  # fill in github_repo_url, etc.

# Step 2 — Bootstrap ECR (must exist before images can be pushed)
# Note: only one ECR repo exists (bitoguard-backend); tags differentiate images
terraform apply -target=aws_ecr_repository.backend -target=aws_ecr_repository.frontend

# Step 3 — ECR login + build + push all three images
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_REGION:-us-west-2}
ECR="$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"

aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $ECR

cd ../../..

# Backend image
docker build -f bitoguard_core/Dockerfile -t bitoguard-backend:latest bitoguard_core/
docker tag bitoguard-backend:latest $ECR/bitoguard-backend:latest
docker push $ECR/bitoguard-backend:latest

# Training image
docker build -f bitoguard_core/Dockerfile.training -t bitoguard-training:latest bitoguard_core/
docker tag bitoguard-training:latest $ECR/bitoguard-backend:training
docker push $ECR/bitoguard-backend:training

# Processing image
docker build -f bitoguard_core/Dockerfile.processing -t bitoguard-processing:latest bitoguard_core/
docker tag bitoguard-processing:latest $ECR/bitoguard-backend:processing
docker push $ECR/bitoguard-backend:processing

# Step 4 — Full Terraform apply
cd infra/aws/terraform
terraform apply

# Step 5 — Bootstrap EFS with pre-seeded data (run once)
cd ../../..
./scripts/bootstrap-efs.sh

# Step 6 — Verify backend health
ALB_URL=$(cd infra/aws/terraform && terraform output -raw alb_url)
curl https://$ALB_URL/healthz   # expect {"status": "ok"}

# Step 7 — Pre-demo tuning run (run the night before, ~2-3 hours)
STATE_MACHINE=$(cd infra/aws/terraform && terraform output -raw ml_pipeline_state_machine_arn)
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE \
  --name "pre-demo-tuning-$(date +%Y%m%d)" \
  --input '{"enable_tuning": true}'
# Monitor: AWS Console → Step Functions → bitoguard-prod-ml-pipeline

# Step 8 — Demo day (fast mode, triggered from frontend)
# Frontend: click "Run Pipeline" button (calls POST /pipeline/run)
# Or manually:
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE \
  --name "demo-$(date +%Y%m%d-%H%M)" \
  --input '{"enable_tuning": false}'
```

**Note on Terraform state:** Local state (`terraform.tfstate`) is acceptable for this hackathon. The S3 backend in `backend.tf` is intentionally commented out. Do not commit `terraform.tfstate` or `terraform.tfvars` to git.

---

## 6. Acceptance Criteria

- [ ] `terraform apply` completes without errors
- [ ] `GET https://<alb-url>/healthz` returns `{"status": "ok"}`
- [ ] Frontend loads at Amplify URL; `/alerts` page shows data from backend
- [ ] `POST /pipeline/run` returns `{"execution_arn": "arn:aws:states:..."}` and Step Functions execution appears in AWS Console
- [ ] Pre-demo tuning run completes: SageMaker HPO jobs visible in console, best params written to SSM `/bitoguard/ml-pipeline/best_params/*`
- [ ] Trained stacker model appears as `Approved` in SageMaker Model Registry under `bitoguard-prod-stacker-models`
- [ ] Demo-mode pipeline completes in < 30 minutes end-to-end
- [ ] Alert list in frontend (`/alerts`) shows scored users after pipeline completes
- [ ] `GET /metrics/drift` returns drift health report (endpoint exists in `api/main.py`)
- [ ] `GET /metrics/model` returns validation report with P@K metrics

---

## 7. AWS Documentation References

All implementation must consult official AWS docs. Key references:

| Component | AWS Reference |
|-----------|--------------|
| ECS Fargate task definitions | https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html |
| EFS volumes in ECS | https://docs.aws.amazon.com/AmazonECS/latest/developerguide/efs-volumes.html |
| SageMaker Training containers | https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms-training-algo-running-container.html |
| SageMaker Hyperparameter Tuning | https://docs.aws.amazon.com/sagemaker/latest/dg/automatic-model-tuning.html |
| SageMaker Model Registry | https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html |
| SageMaker Processing Jobs | https://docs.aws.amazon.com/sagemaker/latest/dg/processing-job.html |
| Step Functions ASL | https://docs.aws.amazon.com/step-functions/latest/dg/concepts-amazon-states-language.html |
| Step Functions intrinsic functions | https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-intrinsic-functions.html |
| Step Functions + API Gateway | https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-api-gateway.html |
| AWS Amplify Next.js SSR | https://docs.aws.amazon.com/amplify/latest/userguide/server-side-rendering-amplify.html |
| Amplify Terraform resource | https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/amplify_app |
| ECR authentication | https://docs.aws.amazon.com/AmazonECR/latest/userguide/registry_auth.html |
