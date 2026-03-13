#!/usr/bin/env bash
# Deploy BitoGuard to AWS ECS.
# Builds and pushes images, registers task definitions, and updates services.
# Usage: ./scripts/deploy_aws.sh <ACCOUNT_ID> <REGION>
#
# Prerequisites:
#   - AWS CLI configured with sufficient permissions
#   - infra/aws/task-def-backend.json and task-def-frontend.json updated with actual values
#   - ECS cluster 'bitoguard' already created
#   - ECS services 'bitoguard-backend' and 'bitoguard-frontend' already created

set -euo pipefail

ACCOUNT_ID="${1:?Usage: $0 <ACCOUNT_ID> <REGION>}"
REGION="${2:?Usage: $0 <ACCOUNT_ID> <REGION>}"
CLUSTER="bitoguard"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[deploy_aws] Step 1: Build and push images..."
"${REPO_ROOT}/scripts/build_and_push.sh" "${ACCOUNT_ID}" "${REGION}"

echo "[deploy_aws] Step 2: Register backend task definition..."
BACKEND_TASK_ARN=$(aws ecs register-task-definition \
  --cli-input-json "file://${REPO_ROOT}/infra/aws/task-def-backend.json" \
  --region "${REGION}" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)
echo "  Backend task definition: ${BACKEND_TASK_ARN}"

echo "[deploy_aws] Step 3: Register frontend task definition..."
FRONTEND_TASK_ARN=$(aws ecs register-task-definition \
  --cli-input-json "file://${REPO_ROOT}/infra/aws/task-def-frontend.json" \
  --region "${REGION}" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)
echo "  Frontend task definition: ${FRONTEND_TASK_ARN}"

echo "[deploy_aws] Step 4: Update backend ECS service..."
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service bitoguard-backend \
  --task-definition "${BACKEND_TASK_ARN}" \
  --force-new-deployment \
  --region "${REGION}" \
  --output text --query 'service.status' | grep -q "ACTIVE"
echo "  Backend service update initiated."

echo "[deploy_aws] Step 5: Update frontend ECS service..."
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service bitoguard-frontend \
  --task-definition "${FRONTEND_TASK_ARN}" \
  --force-new-deployment \
  --region "${REGION}" \
  --output text --query 'service.status' | grep -q "ACTIVE"
echo "  Frontend service update initiated."

echo "[deploy_aws] Step 6: Waiting for services to stabilize..."
aws ecs wait services-stable \
  --cluster "${CLUSTER}" \
  --services bitoguard-backend bitoguard-frontend \
  --region "${REGION}"

echo "[deploy_aws] Deployment complete."

# Quick health check
BACKEND_IP=$(aws ecs describe-tasks \
  --cluster "${CLUSTER}" \
  --tasks "$(aws ecs list-tasks --cluster ${CLUSTER} --service-name bitoguard-backend --query 'taskArns[0]' --output text --region ${REGION})" \
  --region "${REGION}" \
  --query 'tasks[0].attachments[0].details[?name==`privateIPv4Address`].value' \
  --output text 2>/dev/null || echo "")

if [ -n "${BACKEND_IP}" ]; then
  echo "[deploy_aws] Backend IP: ${BACKEND_IP}"
  echo "[deploy_aws] Health check: http://${BACKEND_IP}:8001/healthz"
fi
