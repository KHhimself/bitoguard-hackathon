#!/usr/bin/env bash
# Build and push BitoGuard Docker images to ECR.
# Usage: ./scripts/build_and_push.sh <ACCOUNT_ID> <REGION>
#
# Example: ./scripts/build_and_push.sh 123456789012 ap-northeast-1

set -euo pipefail

ACCOUNT_ID="${1:?Usage: $0 <ACCOUNT_ID> <REGION>}"
REGION="${2:?Usage: $0 <ACCOUNT_ID> <REGION>}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/bitoguard-backend"
FRONTEND_IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/bitoguard-frontend"

echo "[build_and_push] Authenticating Docker to ECR..."
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "[build_and_push] Building backend image..."
docker build \
  -f "${REPO_ROOT}/bitoguard_core/Dockerfile" \
  -t "bitoguard-backend:latest" \
  "${REPO_ROOT}"

echo "[build_and_push] Tagging and pushing backend image..."
docker tag "bitoguard-backend:latest" "${BACKEND_IMAGE}:latest"
docker push "${BACKEND_IMAGE}:latest"

echo "[build_and_push] Building frontend image..."
docker build \
  -f "${REPO_ROOT}/bitoguard_frontend/Dockerfile" \
  --build-arg "BITOGUARD_INTERNAL_API_BASE=http://bitoguard-backend.bitoguard.local:8001" \
  -t "bitoguard-frontend:latest" \
  "${REPO_ROOT}"

echo "[build_and_push] Tagging and pushing frontend image..."
docker tag "bitoguard-frontend:latest" "${FRONTEND_IMAGE}:latest"
docker push "${FRONTEND_IMAGE}:latest"

echo "[build_and_push] Done."
echo "  Backend:  ${BACKEND_IMAGE}:latest"
echo "  Frontend: ${FRONTEND_IMAGE}:latest"
