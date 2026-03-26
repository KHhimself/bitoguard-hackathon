---
inclusion: always
---

# BitoGuard Project Structure

## Directory Organization

**Backend (`bitoguard_core/`)**: Python ML/API system
- `api/` - FastAPI endpoints
- `db/` - DuckDB schema and Store abstraction
- `features/` - Feature engineering (~155 features), register all in `registry.py`
- `models/` - ML training, scoring, rule engine
- `pipeline/` - Data sync and incremental refresh
- `services/` - Business logic (alerts, explanations, drift)
- `ml_pipeline/` - AWS SageMaker integration (preprocessing, training, tuning, model registry)
- `tests/` - pytest suite (mirror source structure)
- `artifacts/` - Generated outputs (NEVER commit, gitignored)

**Frontend (`bitoguard_frontend/`)**: Next.js App Router
- `src/app/` - Route pages and API proxies
- `src/components/` - React components (domain-organized)
- `src/lib/` - Utilities and API clients

**Infrastructure (`infra/aws/`)**: AWS resources
- `terraform/` - IaC modules (*.tf files)
- `lambda/` - Lambda function handlers

**Other**: `scripts/` (deployment), `docs/` (architecture guides)

## Module Placement Rules

**Backend Python:**
- Feature calculation → `features/<domain>_features.py` + register in `features/registry.py`
- ML algorithm → `models/train_<algorithm>.py` (local) OR `ml_pipeline/<component>.py` (SageMaker)
- AML rule → `models/rule_engine.py` (add to RULES dict)
- Pipeline step → `pipeline/<step_name>.py`
- API endpoint → `api/main.py` (FastAPI route)
- Business logic → `services/<service_name>.py`
- Test → `tests/test_<module>.py` (mirror source structure)

**Frontend TypeScript:**
- Page → `src/app/<route>/page.tsx`
- Component → `src/components/<domain>/<ComponentName>.tsx`
- API proxy → `src/app/api/backend/<route>/route.ts`
- Utility → `src/lib/<utility>.ts`

**Infrastructure:**
- Lambda → `infra/aws/lambda/<function_name>/lambda_function.py` (handler: `lambda_function.lambda_handler`)
- Terraform → `infra/aws/terraform/<resource_type>.tf`
- Script → `scripts/<action>-<target>.sh`

## Execution Rules (CRITICAL)

**Python Backend:**
- ALWAYS run from `bitoguard_core/` with `PYTHONPATH=.`
- Use absolute imports: `from db.store import Store` (NOT `from ..db.store`)
- Commands: `cd bitoguard_core && PYTHONPATH=. python -m <module>` or `PYTHONPATH=. pytest tests/`

**Frontend:**
- Run from `bitoguard_frontend/`: `npm run dev` (port 3000)
- Validation required: `npm run lint && npm run build`
- Use `@/` import alias: `import { AlertCard } from '@/components/alerts/AlertCard'`

## Naming Conventions

**Python:**
- Files/modules: `snake_case.py` (e.g., `build_features_v2.py`)
- Tests: `test_<module>.py` (e.g., `test_rule_engine.py`)
- Classes: `PascalCase` (e.g., `class FeatureStore`)
- Functions/variables: `snake_case` (e.g., `def build_feature_snapshot()`)

**TypeScript:**
- Components: `PascalCase.tsx` (e.g., `AlertCard.tsx`)
- Routes: `page.tsx` (Next.js convention)
- Utilities: `camelCase.ts` or `kebab-case.ts`
- Variables/functions: `camelCase`

**Infrastructure:**
- Terraform: `<resource_type>.tf` (e.g., `sagemaker_training.tf`)
- Lambda: `lambda_function.py` (AWS convention)
- Scripts: `<action>-<target>.sh` (e.g., `deploy-ml-pipeline.sh`)

## Artifacts (NEVER Commit)

Generated files in `bitoguard_core/artifacts/` (gitignored):
- Models: `models/<algo>_<timestamp>.joblib` + `.sha256` checksum
- Metadata: `models/cv_results_<timestamp>.json`
- Database: `bitoguard.duckdb` (DuckDB embedded)
- Reports: `reports/alert_<id>.json`, `drift_report.json`
- Timestamps: ISO 8601 format `YYYYMMDDTHHMMSSZ`

## Configuration Hierarchy

**Backend:** `config.py` defaults → Environment variables → AWS SSM Parameter Store (`/bitoguard/{env}/ml/config`)

**Frontend:** `.env.local` (dev, gitignored) → Environment variables (prod)

**Infrastructure:** `terraform.tfvars` (gitignored) → `variables.tf` defaults → SSM Parameter Store

**Security:** NEVER commit secrets, API keys, or `.env` files. Use environment variables or SSM.

## Testing Requirements

**Backend:** Run `cd bitoguard_core && PYTHONPATH=. pytest tests/` before commits
- Test files mirror source: `tests/test_<module>.py` for `<module>.py`
- Use fixtures from `tests/conftest.py`
- Cover: rules, features, models, graph, store, pipeline

**Frontend:** Run `npm run lint && npm run build` before commits (no test framework yet)

**Infrastructure:** Run `terraform fmt -check -recursive && terraform validate` before commits

## Common Implementation Patterns

**Add feature:**
1. Create `features/<domain>_features.py` with builder function
2. Register in `features/registry.py` with human-readable description
3. Add tests in `tests/test_<domain>_features.py`
4. Verify no future data leakage (temporal correctness)
5. Retrain models, check precision@K impact

**Add API endpoint:**
1. Add route to `api/main.py` (FastAPI)
2. Use `db/store.py` Store abstraction
3. Return Pydantic models for validation
4. Test with curl or Postman

**Add Lambda:**
1. Create `infra/aws/lambda/<name>/lambda_function.py` (handler: `lambda_function.lambda_handler`)
2. Add Terraform resource in `infra/aws/terraform/lambda.tf`
3. Use boto3 for AWS SDK, log structured JSON to CloudWatch

**Modify ML pipeline:**
1. Local: update `models/train.py` or `features/build_features_v2.py`
2. AWS: update `ml_pipeline/` entrypoints and `infra/aws/terraform/`
3. Test locally first, deploy to dev, monitor drift/performance
