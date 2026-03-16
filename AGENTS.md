# Repository Guidelines

## Project Structure & Module Organization
`bitoguard_core/` contains the Python backend: FastAPI endpoints in `api/`, data access in `db/`, feature builders in `features/`, pipelines in `pipeline/`, models in `models/`, services in `services/`, and pytest suites in `tests/`. Generated data and model outputs live in `bitoguard_core/artifacts/`.

`bitoguard_frontend/` is a Next.js App Router app with routes in `src/app/`, shared UI in `src/components/`, and static assets in `public/`. AWS infrastructure lives in `infra/aws/terraform/` and `infra/aws/lambda/`; runbooks and deployment notes live in `docs/` and `deploy/`.

## Build, Test, and Development Commands
- `make setup`: create `bitoguard_core/.venv` and install backend dependencies.
- `make test` or `make test-quick`: run the backend pytest suite.
- `make serve`: start FastAPI on `http://localhost:8001`.
- `cd bitoguard_frontend && npm ci && npm run dev`: install frontend deps and start Next.js on `http://localhost:3000`.
- `cd bitoguard_frontend && npm run lint && npm run build`: required frontend validation.
- `docker compose up --build`: run the full stack locally.
- `cd infra/aws/terraform && terraform fmt -check -recursive && terraform validate`: required for Terraform changes.

## Coding Style & Naming Conventions
Python uses 4-space indentation, type hints, and `snake_case` for functions, modules, and tests. Keep backend code domain-focused and colocated with the existing package structure. Frontend code uses strict TypeScript, React function components, `PascalCase` component files such as `Sidebar.tsx`, and route files like `src/app/alerts/page.tsx`. Follow the existing frontend style: double quotes, no semicolons, and Tailwind utility classes.

## Testing Guidelines
Add or update pytest cases for every backend behavior change in `bitoguard_core/`. Name files `test_*.py` and prefer focused fixture-driven cases using `bitoguard_core/tests/conftest.py`. There is no dedicated frontend test harness yet, so treat `npm run lint` and `npm run build` as the minimum gate for UI work.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commit prefixes: `feat:`, `fix:`, `chore:`, and `docs:`. Keep subjects imperative and scoped to one change. PRs should include a short summary, linked issue or context, exact validation commands run, and screenshots for UI changes. For Docker or infra changes, note required env vars such as `BITOGUARD_API_KEY` and confirm `docker compose build` or Terraform validation passed.

## Security & Configuration Tips
Start from `deploy/.env.compose.example` for Docker and `bitoguard_frontend/.env.example` for frontend configuration. Do not commit secrets, generated artifacts, or ad hoc database files. Preserve `BITOGUARD_GRAPH_FEATURES_TRUSTED_ONLY=true` unless you are intentionally changing the graph trust boundary and updating the corresponding docs.
