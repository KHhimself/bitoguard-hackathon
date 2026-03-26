---
inclusion: always
---

# BitoGuard Technology Stack

## Python Backend (bitoguard_core/)

Stack: Python 3.x, DuckDB 1.3.2, FastAPI 0.116.1, LightGBM 4.6.0, CatBoost 1.2+, scikit-learn 1.7.1, SHAP 0.48.0, NetworkX 3.5, pandas 2.3.2, pytest 8.4.1

### CRITICAL: Python Execution Context

ALL Python commands MUST run from `bitoguard_core/` directory with `PYTHONPATH=.`:

```bash
cd bitoguard_core
PYTHONPATH=. python -m <module>
PYTHONPATH=. pytest tests/
PYTHONPATH=. uvicorn api.main:app --reload --port 8001
```

NEVER use relative imports. Use absolute imports only:

```python
# CORRECT
from db.store import Store
from features.build_features_v2 import build_feature_snapshot

# FORBIDDEN
from ..db.store import Store
from .store import Store
```

### Code Style & Conventions

Naming:
- `snake_case`: functions, variables, modules, files (e.g., `build_features_v2.py`, `def calculate_risk()`)
- `PascalCase`: classes only (e.g., `class FeatureStore`)
- One domain per module (e.g., `crypto_features.py`, `graph_features.py`)

Formatting:
- Type hints required on all function signatures
- 4-space indentation (no tabs)
- Google-style docstrings for public functions
- Line length: 100 characters (soft limit)

Testing:
- Mirror source structure: `tests/test_<module>.py` for `<module>.py`
- Use fixtures from `tests/conftest.py`
- Run before commits: `cd bitoguard_core && PYTHONPATH=. pytest tests/`
- Test coverage: focus on business logic, rules, features, models

### Environment Variables

Required:
- `BITOGUARD_API_KEY`: Internal API authentication (NEVER commit)
- `PYTHONPATH`: Must be `.` when running from bitoguard_core/

Optional:
- `BITOGUARD_SOURCE_URL`: BitoPro API endpoint (default: https://aws-event-api.bitopro.com)
- `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY`: Graph trust boundary (default: true)

## TypeScript Frontend (bitoguard_frontend/)

Stack: Next.js 16.1.6 App Router, React 19.2.3, TypeScript 5 strict mode, Tailwind CSS 4, Radix UI, TanStack Query 5.90.21

### Code Style & Conventions

Naming:
- `PascalCase`: components and component files (e.g., `AlertCard.tsx`, `UserProfile.tsx`)
- `camelCase`: variables, functions, hooks (e.g., `const userName`, `function fetchAlerts()`)
- Routes: `src/app/<route>/page.tsx` (Next.js App Router convention)
- API routes: `src/app/api/backend/<route>/route.ts`

Formatting:
- TypeScript strict mode: no `any` types (use `unknown` if type is truly unknown)
- Function components with hooks only (no class components)
- Double quotes for strings, no semicolons
- Import alias: `@/` maps to `src/` (e.g., `import { AlertCard } from '@/components/alerts/AlertCard'`)
- Tailwind utility classes for styling (avoid inline styles)

Validation before commits:
```bash
cd bitoguard_frontend
npm run lint && npm run build
```

Environment Variables:
- `BITOGUARD_INTERNAL_API_BASE`: Backend URL (default: http://127.0.0.1:8001)
- `BITOGUARD_INTERNAL_API_KEY`: Backend API key
- Use `.env.local` for development (NEVER commit)

## AWS Infrastructure (infra/aws/)

Stack: Terraform 1.x, ECS Fargate, SageMaker, Step Functions, Lambda (Python 3.x), EFS, SSM Parameter Store, CloudWatch

### Naming Conventions

Resources:
- Pattern: `bitoguard-{env}-{resource}` (e.g., `bitoguard-prod-backend`, `bitoguard-dev-ecs-cluster`)
- Environments: `dev`, `staging`, `prod`

Terraform files:
- Resource type per file: `ecs.tf`, `sagemaker_training.tf`, `lambda.tf`, `step_functions.tf`
- Shared: `variables.tf`, `outputs.tf`, `providers.tf`

Lambda functions:
- Directory: `infra/aws/lambda/<function_name>/`
- Handler file: `lambda_function.py`
- Handler function: `lambda_function.lambda_handler`
- Use boto3 for AWS SDK, structured JSON logging to CloudWatch

### Validation & Deployment

Run before commits:
```bash
cd infra/aws/terraform
terraform fmt -check -recursive && terraform validate
```

Deployment scripts:
```bash
./scripts/deploy-ml-pipeline.sh <env>              # ML pipeline infrastructure
./scripts/deploy-full-aws-sagemaker.sh <env>       # Full SageMaker integration
```

NEVER commit:
- `terraform.tfvars` (contains secrets)
- `.terraform/` directory
- `*.tfstate` files

## Common Commands Reference

### Backend (from bitoguard_core/)
```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Development
PYTHONPATH=. uvicorn api.main:app --reload --port 8001

# Testing
PYTHONPATH=. pytest tests/                    # All tests
PYTHONPATH=. pytest tests/test_rules.py       # Specific test file
PYTHONPATH=. pytest -v -s                     # Verbose with output
```

### Frontend (from bitoguard_frontend/)
```bash
# Setup
npm install && cp .env.example .env.local

# Development
npm run dev                                   # Port 3000

# Validation (required before commits)
npm run lint && npm run build
```

### ML Pipeline (from project root)
```bash
make sync      # Fetch data from BitoPro API
make features  # Build ~155 features (point-in-time)
make train     # Train LightGBM/CatBoost models
make score     # Generate risk scores and alerts
make refresh   # Incremental update (watermark-based)
make drift     # Check feature drift
```

### Docker (from project root)
```bash
make docker-build                             # Build images
make docker-up                                # Start: Backend:8001, Frontend:3000
make docker-down                              # Stop and remove containers
docker compose logs -f backend                # View backend logs
```

## Critical Constraints

### Artifacts (NEVER Commit)

Path: `bitoguard_core/artifacts/` (gitignored)

Models:
- Format: `models/<algo>_<timestamp>.joblib` + `.sha256` checksum
- Timestamp: ISO 8601 format `YYYYMMDDTHHMMSSZ` (e.g., `cb_20260316T151027Z.joblib`)
- Metadata: `models/cv_results_<timestamp>.json` (cross-validation results)

Database:
- File: `bitoguard.duckdb` (DuckDB embedded database)
- AWS: EFS mount for persistence
- Tables: `users`, `login_events`, `fiat_transactions`, `crypto_transactions`, `trade_orders`

Reports:
- `reports/alert_<id>.json`: Individual alert details with SHAP explanations
- `drift_report.json`: Feature drift analysis
- `validation_report.json`: Model validation metrics

### Security (MANDATORY)

NEVER commit:
- Secrets, API keys, passwords
- `.env`, `.env.local`, `terraform.tfvars`
- `artifacts/` directory contents
- Database files (`.duckdb`)

Configuration hierarchy (in order of precedence):
1. Environment variables (highest priority)
2. AWS SSM Parameter Store at `/bitoguard/{env}/ml/config`
3. Default values in `config.py`

AWS credentials:
- Use IAM roles only (never hardcode access keys)
- Local development: AWS CLI profiles
- Production: ECS task roles, Lambda execution roles

Required environment variables:
- Backend: `BITOGUARD_API_KEY`
- Frontend: `BITOGUARD_INTERNAL_API_KEY`

### Performance SLAs

Target performance metrics:
- Full data sync: <10 minutes (~100K+ transactions)
- Feature building: <10 minutes (full snapshot with ~155 features)
- API responses: <2 seconds (user 360 view with risk score)
- Incremental refresh: every 15 minutes (production watermark-based)

When optimizing:
1. Profile first (use cProfile, line_profiler)
2. Maintain SLAs
3. Document trade-offs

### Port Assignments

Development:
- Backend API: 8001
- Frontend: 3000

Production:
- ALB: 80 (HTTP), 443 (HTTPS)
- Backend (internal): 8001

## AWS SageMaker ML Pipeline

### Architecture Components

Preprocessing:
- Entrypoint: `ml_pipeline/preprocessing_entrypoint.py`
- Runtime: ECS Fargate task
- Reads from DuckDB, writes features to S3

Training:
- Entrypoint: `ml_pipeline/train_entrypoint.py`
- Runtime: SageMaker training job
- Algorithms: LightGBM, CatBoost
- Outputs: Model artifacts to S3

Hyperparameter Tuning:
- SageMaker automatic model tuning
- Analyzer: Lambda function `tuning_analyzer`
- Optimizes for precision@K

Model Registry:
- SageMaker model packages
- Approval workflow: Lambda function `model_registry`
- Versioning and lineage tracking

Orchestration:
- Step Functions state machine
- Coordinates: preprocessing → training → tuning → registration
- Error handling and retries

### Configuration Management

Location: SSM Parameter Store at `/bitoguard/{env}/ml/config`

Load in code:
```python
from ml_pipeline.config_loader import load_ml_config
config = load_ml_config()
```

Update via:
- AWS Console: Systems Manager → Parameter Store
- Terraform: `infra/aws/terraform/ssm_parameters.tf`
- Validation: Lambda function `config_validator`

### Deployment

Pipeline infrastructure:
```bash
./scripts/deploy-ml-pipeline.sh <env>
```

Full SageMaker integration:
```bash
./scripts/deploy-full-aws-sagemaker.sh <env>
```

### Lambda Functions

- `drift_detector`: Monitor feature drift, trigger retraining
- `config_validator`: Validate ML config changes before apply
- `manual_trigger`: Manually trigger pipeline execution
- `tuning_analyzer`: Analyze hyperparameter tuning results
- `model_registry`: Handle model approval workflow

All Lambda functions:
- Runtime: Python 3.x
- Handler: `lambda_function.lambda_handler`
- Logging: Structured JSON to CloudWatch
- IAM: Least privilege execution roles

### Key Files

Configuration:
- `bitoguard_core/ml_pipeline/config_loader.py`: Load SSM config
- `infra/aws/terraform/ssm_parameters.tf`: Config definitions

Entrypoints:
- `bitoguard_core/ml_pipeline/preprocessing_entrypoint.py`: Feature prep
- `bitoguard_core/ml_pipeline/train_entrypoint.py`: Model training

Infrastructure:
- `infra/aws/terraform/ml_pipeline.tf`: Core pipeline resources
- `infra/aws/terraform/step_functions.tf`: Orchestration
- `infra/aws/terraform/sagemaker_training.tf`: Training jobs
- `infra/aws/terraform/sagemaker_tuning.tf`: Hyperparameter tuning
- `infra/aws/terraform/sagemaker_model_registry.tf`: Model registry

Utilities:
- `bitoguard_core/ml_pipeline/artifact_manager.py`: S3 artifact handling
- `bitoguard_core/ml_pipeline/feature_store.py`: Feature storage abstraction
