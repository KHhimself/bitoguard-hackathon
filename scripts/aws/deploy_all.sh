#!/usr/bin/env bash
# BitoGuard E15 — 一鍵全自動部署到 AWS。
#
# 用法：
#   ./scripts/aws/deploy_all.sh <ACCOUNT_ID> [REGION] [BUCKET]
#
# 範例：
#   ./scripts/aws/deploy_all.sh 123456789012
#   ./scripts/aws/deploy_all.sh 123456789012 ap-northeast-1 my-bucket
#
# 此腳本依序執行：
#   1. build_and_push.sh   → 建置 Docker image → ECR
#   2. upload_data.py      → BitoPro API → parquet → S3
#   3. launch_training.py  → SageMaker Training Job（等待完成）
#   4. deploy_endpoint.py  → SageMaker Endpoint（等待 InService）

set -euo pipefail

ACCOUNT_ID="${1:?用法: $0 <ACCOUNT_ID> [REGION] [BUCKET]}"
REGION="${2:-ap-northeast-1}"
BUCKET="${3:-bitoguard-e15-data}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================================"
echo "BitoGuard E15 — 完整 AWS 部署"
echo "========================================================"
echo "  帳號:   ${ACCOUNT_ID}"
echo "  區域:   ${REGION}"
echo "  Bucket: ${BUCKET}"
echo "  時間:   $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "========================================================"
echo ""

# ── Step 1: Build & Push Docker Image ─────────────────────────────────────
echo "=========================================="
echo "[Step 1/4] 建置 & 推送 Docker Image"
echo "=========================================="
bash "${SCRIPT_DIR}/build_and_push.sh" "${ACCOUNT_ID}" "${REGION}"
echo ""

# ── Step 2: 上傳資料到 S3 ─────────────────────────────────────────────────
echo "=========================================="
echo "[Step 2/4] 下載 BitoPro 資料 & 上傳 S3"
echo "=========================================="
python3 "${SCRIPT_DIR}/upload_data.py" \
  --bucket "${BUCKET}" \
  --region "${REGION}"
echo ""

# ── Step 3: 啟動 SageMaker Training ──────────────────────────────────────
echo "=========================================="
echo "[Step 3/4] 啟動 SageMaker Training Job"
echo "=========================================="
# 擷取 training output 的 model.tar.gz 路徑
TRAINING_OUTPUT=$(python3 "${SCRIPT_DIR}/launch_training.py" \
  --account-id "${ACCOUNT_ID}" \
  --region "${REGION}" \
  --bucket "${BUCKET}" \
  2>&1 | tee /dev/stderr)

# 從 output 中擷取 Model Artifacts S3 URI
MODEL_DATA=$(echo "${TRAINING_OUTPUT}" | grep "Model Artifacts:" | awk '{print $NF}')
if [ -z "${MODEL_DATA}" ]; then
  echo "[錯誤] 無法取得 model.tar.gz 路徑。訓練可能失敗。"
  echo "  請手動執行 deploy_endpoint.py 並指定 --model-data。"
  exit 1
fi
echo ""
echo "  Model Data: ${MODEL_DATA}"
echo ""

# ── Step 4: 部署 SageMaker Endpoint ──────────────────────────────────────
echo "=========================================="
echo "[Step 4/4] 部署 SageMaker Endpoint"
echo "=========================================="
python3 "${SCRIPT_DIR}/deploy_endpoint.py" \
  --account-id "${ACCOUNT_ID}" \
  --region "${REGION}" \
  --model-data "${MODEL_DATA}"

echo ""
echo "========================================================"
echo "部署完成！"
echo "========================================================"
echo ""
echo "資源清單："
echo "  ECR Image:   ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/bitoguard-e15-training:latest"
echo "  S3 Bucket:   s3://${BUCKET}/raw/"
echo "  Endpoint:    bitoguard-e15-endpoint"
echo ""
echo "測試 endpoint："
echo "  aws sagemaker-runtime invoke-endpoint \\"
echo "    --endpoint-name bitoguard-e15-endpoint \\"
echo "    --content-type application/json \\"
echo "    --body '{\"instances\": [{\"user_id\": \"test\"}]}' \\"
echo "    --region ${REGION} \\"
echo "    output.json"
echo ""
echo "清理資源（Demo 完畢後）："
echo "  aws sagemaker delete-endpoint --endpoint-name bitoguard-e15-endpoint --region ${REGION}"
echo "  aws sagemaker delete-endpoint-config --endpoint-config-name \$(aws sagemaker list-endpoint-configs --region ${REGION} --query 'EndpointConfigs[?starts_with(EndpointConfigName,\`bitoguard-e15\`)].EndpointConfigName' --output text)"
echo "  aws s3 rm s3://${BUCKET} --recursive"
