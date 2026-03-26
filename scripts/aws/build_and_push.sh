#!/usr/bin/env bash
# 建置 E15 訓練 Docker image 並推送到 ECR。
#
# 用法：
#   ./scripts/aws/build_and_push.sh <ACCOUNT_ID> <REGION>
#
# 範例：
#   ./scripts/aws/build_and_push.sh 123456789012 ap-northeast-1
#
# 產出：
#   ECR image: <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/bitoguard-e15-training:latest
#
# 此 image 同時用於 SageMaker Training 和 Inference（只差 ENTRYPOINT）。
# Training: ENTRYPOINT → sagemaker_e15_train.py
# Inference: SageMaker 會用 gunicorn 啟動 serve_e15.py

set -euo pipefail

ACCOUNT_ID="${1:?用法: $0 <ACCOUNT_ID> <REGION>}"
REGION="${2:-ap-northeast-1}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_NAME="bitoguard-e15-training"
IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"
TAG="latest"

echo "============================================"
echo "BitoGuard E15 — Docker Build & Push to ECR"
echo "============================================"
echo "  帳號: ${ACCOUNT_ID}"
echo "  區域: ${REGION}"
echo "  映像: ${IMAGE_URI}:${TAG}"
echo ""

# Step 1: 確保 ECR repo 存在
echo "[1/4] 建立 ECR repository（如果不存在）..."
aws ecr describe-repositories \
  --repository-names "${REPO_NAME}" \
  --region "${REGION}" 2>/dev/null || \
aws ecr create-repository \
  --repository-name "${REPO_NAME}" \
  --region "${REGION}" \
  --image-scanning-configuration scanOnPush=true

# Step 2: Docker 登入 ECR
echo "[2/4] Docker 登入 ECR..."
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin \
  "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

# Step 3: Build image
echo "[3/4] 建置 Docker image..."
docker build \
  -f "${REPO_ROOT}/bitoguard_core/Dockerfile.training" \
  -t "${REPO_NAME}:${TAG}" \
  "${REPO_ROOT}/bitoguard_core"

# Step 4: Tag & Push
echo "[4/4] 推送到 ECR..."
docker tag "${REPO_NAME}:${TAG}" "${IMAGE_URI}:${TAG}"
docker push "${IMAGE_URI}:${TAG}"

echo ""
echo "完成！"
echo "  Image URI: ${IMAGE_URI}:${TAG}"
echo ""
echo "下一步："
echo "  1. 上傳資料:    python scripts/aws/upload_data.py --region ${REGION}"
echo "  2. 啟動訓練:    python scripts/aws/launch_training.py --account-id ${ACCOUNT_ID} --region ${REGION}"
