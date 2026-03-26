# BitoGuard Project Structure

## Repository Layout

```
bitoguard/
├── bitoguard_core/          # Python backend (AML engine)
├── bitoguard_frontend/      # Next.js frontend (dashboard)
├── infra/                   # Infrastructure as code
│   └── aws/                 # AWS deployment (Terraform)
├── scripts/                 # Deployment and utility scripts
├── docs/                    # Documentation
├── .github/workflows/       # CI/CD pipelines
├── Makefile                 # Task orchestration
└── docker-compose.yml       # Local development stack
```

## Backend Structure (bitoguard_core/)

### Core Modules

```
bitoguard_core/
├── api/                     # FastAPI endpoints
│   └── main.py             # API server with 13 endpoints
├── db/                      # Database layer
│   ├── schema.py           # DuckDB table definitions
│   └── store.py            # Data access layer
├── features/                # Feature engineering
│   ├── build_features.py   # Statistical features (peer deviation, rolling windows)
│   ├── build_features_v2.py # Enhanced feature set (~155 columns)
│   ├── graph_features.py   # NetworkX graph analysis
│   ├── graph_bipartite.py  # Bipartite graph construction
│   ├── graph_propagation.py # Risk propagation algorithms
│   ├── crypto_features.py  # Crypto-specific features
│   ├── ip_features.py      # IP-based features
│   ├── profile_features.py # User profile features
│   ├── sequence_features.py # Temporal sequence features
│   ├── swap_features.py    # Swap transaction features
│   ├── trading_features.py # Trading pattern features
│   ├── twd_features.py     # TWD fiat features
│   └── registry.py         # Feature registry
├── models/                  # ML models
│   ├── train.py            # LightGBM training
│   ├── train_catboost.py   # CatBoost training
│   ├── anomaly.py          # IsolationForest anomaly detection
│   ├── stacker.py          # Ensemble stacking (CatBoost + LightGBM + LR)
│   ├── score.py            # Risk scoring engine
│   ├── validate.py         # Model evaluation (P@K, calibration)
│   ├── rule_engine.py      # 11 deterministic AML rules
│   ├── dormancy.py         # Dormancy detection
│   └── common.py           # Shared model utilities
├── pipeline/                # Data pipeline
│   ├── sync.py             # Full data sync from BitoPro
│   ├── sync_source.py      # Source API client
│   ├── load_oracle.py      # Oracle data loading
│   ├── normalize.py        # Data normalization
│   ├── rebuild_edges.py    # Graph edge reconstruction
│   ├── refresh_live.py     # Incremental watermark refresh
│   └── transformers.py     # Data transformations
├── services/                # Business logic services
│   ├── alert_engine.py     # Alert generation and management
│   ├── diagnosis.py        # Risk diagnosis with SHAP
│   ├── drift.py            # Feature drift detection
│   └── explain.py          # Model explainability
├── tests/                   # Test suite (61 tests)
│   ├── conftest.py         # pytest fixtures
│   ├── test_smoke.py       # Smoke tests
│   ├── test_rule_engine.py # Rule engine tests
│   ├── test_model_pipeline.py # End-to-end pipeline tests
│   ├── test_graph_*.py     # Graph analysis tests
│   ├── test_stacker.py     # Ensemble tests
│   └── test_store.py       # Database tests
├── artifacts/               # Generated artifacts (gitignored)
│   ├── bitoguard.duckdb    # Main database
│   ├── models/             # Trained model files (.pkl, .json)
│   └── reports/            # Alert reports
├── config.py               # Configuration management
├── source_client.py        # BitoPro API client
├── oracle_client.py        # Oracle data client
└── requirements.txt        # Python dependencies
```

### Module Responsibilities

- **api/**: REST API endpoints for frontend integration
- **db/**: Database schema and data access abstraction
- **features/**: All feature engineering logic (statistical, graph, domain-specific)
- **models/**: ML model training, scoring, and evaluation
- **pipeline/**: Data ingestion, transformation, and refresh
- **services/**: High-level business logic (alerts, explanations, drift)
- **tests/**: Comprehensive test coverage

## Frontend Structure (bitoguard_frontend/)

```
bitoguard_frontend/
├── src/
│   ├── app/                # Next.js App Router pages
│   │   ├── page.tsx        # Home/dashboard
│   │   ├── alerts/         # Alert list and detail pages
│   │   ├── users/          # User 360 view
│   │   ├── metrics/        # Model metrics dashboard
│   │   └── api/            # API proxy routes
│   │       └── backend/    # Proxy to bitoguard_core
│   ├── components/         # React components
│   │   ├── ui/             # Reusable UI components (Radix)
│   │   └── [feature]/      # Feature-specific components
│   └── lib/                # Utilities and helpers
├── public/                 # Static assets
├── .env.example            # Environment template
└── package.json            # Node dependencies
```

## Infrastructure (infra/)

```
infra/
└── aws/
    ├── terraform/          # Terraform IaC
    │   ├── main.tf         # Provider config
    │   ├── vpc.tf          # Network infrastructure
    │   ├── ecs.tf          # ECS Fargate services
    │   ├── alb.tf          # Load balancer
    │   ├── ecr.tf          # Container registry
    │   ├── efs.tf          # Persistent storage
    │   ├── iam.tf          # IAM roles/policies
    │   ├── cloudwatch.tf   # Logging/monitoring
    │   ├── autoscaling.tf  # Auto-scaling policies
    │   └── secrets.tf      # Secrets Manager
    └── ARCHITECTURE.md     # AWS architecture docs
```

## Key Conventions

### Python Code Organization
- All modules run with `PYTHONPATH=.` from `bitoguard_core/` directory
- Use relative imports within modules: `from db.store import Store`
- Configuration via `config.py` and environment variables
- Tests mirror source structure in `tests/` directory

### Frontend Code Organization
- App Router structure: `app/[route]/page.tsx`
- API proxy pattern: `/api/backend/*` routes to backend
- Component library: Radix UI + Tailwind CSS
- Type safety: TypeScript with strict mode

### Artifact Storage
- Models: `bitoguard_core/artifacts/models/`
- Database: `bitoguard_core/artifacts/bitoguard.duckdb`
- Reports: `bitoguard_core/artifacts/reports/`
- All artifacts are gitignored

### Testing
- Backend tests: Run from `bitoguard_core/` with `PYTHONPATH=. pytest tests/`
- Frontend tests: Run from `bitoguard_frontend/` with `npm run lint`
- Integration tests cover full pipeline: sync → features → train → score

### Deployment Artifacts
- Docker images: Built from root-level Dockerfiles in each service
- Terraform state: Stored locally or in S3 backend
- Environment configs: `.env` files (never committed)

## File Naming Patterns

- Python modules: `snake_case.py`
- TypeScript/React: `kebab-case.tsx` or `PascalCase.tsx` for components
- Config files: `lowercase.extension` (e.g., `config.py`, `tsconfig.json`)
- Documentation: `UPPERCASE.md` for top-level, `lowercase.md` for nested

## Import Patterns

### Backend (Python)
```python
# Absolute imports from project root
from db.store import Store
from features.build_features import build_feature_snapshot
from models.train import train_model

# Always run with PYTHONPATH=.
```

### Frontend (TypeScript)
```typescript
// Relative imports
import { AlertCard } from '@/components/alerts/AlertCard'
import { fetchAlerts } from '@/lib/api'
```

## Configuration Management

- Backend: `config.py` + environment variables
- Frontend: `.env.local` for local dev, environment variables in production
- Infrastructure: `terraform.tfvars` for AWS resources
- Never commit secrets or API keys
