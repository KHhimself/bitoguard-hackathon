# BitoGuard Technology Stack

## Backend (bitoguard_core)

### Core Technologies
- **Language**: Python 3.x
- **Database**: DuckDB 1.3.2 (embedded analytical database)
- **API Framework**: FastAPI 0.116.1 + Uvicorn 0.35.0
- **ML Libraries**: 
  - LightGBM 4.6.0 (gradient boosting)
  - scikit-learn 1.7.1 (preprocessing, metrics)
  - CatBoost 1.2+ (ensemble stacking)
- **Explainability**: SHAP 0.48.0 (model explanations)
- **Graph Analysis**: NetworkX 3.5
- **Data Processing**: pandas 2.3.2, pyarrow 21.0.0
- **HTTP Client**: httpx 0.28.1
- **Testing**: pytest 8.4.1

### Environment Setup
```bash
cd bitoguard_core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables
- `BITOGUARD_SOURCE_URL`: BitoPro API endpoint (default: https://aws-event-api.bitopro.com)
- `BITOGUARD_API_KEY`: Internal API authentication key
- `PYTHONPATH`: Set to `.` when running modules

## Frontend (bitoguard_frontend)

### Core Technologies
- **Framework**: Next.js 16.1.6 (App Router)
- **Runtime**: React 19.2.3
- **Language**: TypeScript 5
- **Styling**: Tailwind CSS 4
- **UI Components**: Radix UI, Lucide React
- **Data Fetching**: TanStack Query 5.90.21
- **Graph Visualization**: Cytoscape.js 3.33.1

### Environment Setup
```bash
cd bitoguard_frontend
npm install
cp .env.example .env.local
```

### Environment Variables
- `BITOGUARD_INTERNAL_API_BASE`: Backend API URL (default: http://127.0.0.1:8001)
- `BITOGUARD_INTERNAL_API_KEY`: Backend API key for proxy authentication

## Common Commands

### Backend Development
```bash
# Run tests (61 tests)
make test

# Quick test run
make test-quick

# Start API server (port 8001)
make serve
# or manually:
cd bitoguard_core && source .venv/bin/activate
PYTHONPATH=. uvicorn api.main:app --reload --port 8001
```

### Frontend Development
```bash
# Start dev server (port 3000)
make frontend
# or manually:
cd bitoguard_frontend && npm run dev

# Build for production
npm run build

# Lint
npm run lint
```

### Data Pipeline
```bash
# Full data sync from BitoPro
make sync

# Build feature snapshots
make features

# Train models
make train

# Score users and generate alerts
make score

# Incremental refresh
make refresh

# Check feature drift
make drift
```

### Docker
```bash
# Build images
make docker-build

# Start full stack
make docker-up

# Stop stack
make docker-down
```

### AWS Deployment
```bash
# Initialize infrastructure (one-time)
cd infra/aws/terraform
terraform init
cp terraform.tfvars.example terraform.tfvars
terraform apply

# Deploy application
./scripts/deploy-aws.sh

# Check deployment health
./scripts/check-deployment.sh

# View logs
aws logs tail /ecs/bitoguard-prod-backend --follow

# Rollback
./scripts/rollback-deployment.sh backend 5
```

## Build System

- **Backend**: Python venv + pip (no build step, interpreted)
- **Frontend**: Next.js build system (webpack-based)
- **Orchestration**: Makefile for common tasks
- **Containerization**: Docker + Docker Compose
- **Infrastructure**: Terraform for AWS resources
- **CI/CD**: GitHub Actions workflows

## Testing Strategy

- **Unit Tests**: pytest for backend modules
- **Integration Tests**: Source API integration, model pipeline end-to-end
- **Test Coverage**: 61 tests covering rules, features, models, graph, store
- **Run Location**: Always from `bitoguard_core/` directory with `PYTHONPATH=.`

## API Ports

- Backend API: 8001
- Frontend: 3000
- Production ALB: 80 (HTTP), 443 (HTTPS with certificate)

## Database

- **Type**: DuckDB (embedded, file-based)
- **Location**: `bitoguard_core/artifacts/bitoguard.duckdb`
- **Schema**: users, login_events, fiat_transactions, crypto_transactions, trade_orders
- **Persistence**: EFS in AWS deployment for shared access across tasks
