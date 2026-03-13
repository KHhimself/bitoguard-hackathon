# AWS Runbook

This runbook covers deploying and operating BitoGuard on AWS using ECS Fargate with an Application Load Balancer.

## Architecture Overview

```
Internet
   │
   ▼
CloudFront (optional CDN for frontend)
   │
   ▼
ALB (Application Load Balancer)
   ├── /api/* → ECS Backend Service (bitoguard-backend)
   └── /*     → ECS Frontend Service (bitoguard-frontend)

ECS Cluster (bitoguard)
   ├── bitoguard-backend   (FastAPI, port 8001)
   │     ├── Reads/writes: EFS volume (artifacts + DuckDB)
   │     └── Fetches: https://aws-event-api.bitopro.com
   └── bitoguard-frontend  (Next.js, port 3000)
         └── Reads: backend API via ECS service discovery

EFS (Elastic File System)
   └── /app/bitoguard_core/artifacts/  (DuckDB + model artifacts)

ECR (Elastic Container Registry)
   ├── bitoguard-backend:latest
   └── bitoguard-frontend:latest

CloudWatch Logs
   └── /ecs/bitoguard-{backend,frontend}

EventBridge Scheduler
   └── Cron: refresh_live every 15 minutes
```

## Prerequisites

- AWS CLI configured with sufficient IAM permissions
- Docker installed locally for image builds
- `jq` installed for JSON parsing in scripts

## One-Time Setup

### 1. Create ECR Repositories

```bash
aws ecr create-repository --repository-name bitoguard-backend --region ap-northeast-1
aws ecr create-repository --repository-name bitoguard-frontend --region ap-northeast-1
```

### 2. Create EFS File System

```bash
EFS_ID=$(aws efs create-file-system \
  --performance-mode generalPurpose \
  --throughput-mode bursting \
  --query 'FileSystemId' --output text \
  --region ap-northeast-1)
echo "EFS_ID: $EFS_ID"

# Create mount targets in each AZ subnet
for SUBNET_ID in subnet-aaa subnet-bbb subnet-ccc; do
  aws efs create-mount-target \
    --file-system-id $EFS_ID \
    --subnet-id $SUBNET_ID \
    --security-groups sg-bitoguard-efs \
    --region ap-northeast-1
done
```

### 3. Create ECS Cluster

```bash
aws ecs create-cluster --cluster-name bitoguard --region ap-northeast-1
```

### 4. Create IAM Roles

**Task Execution Role** (pulls images, reads secrets):
```bash
aws iam create-role \
  --role-name bitoguard-task-execution-role \
  --assume-role-policy-document file://infra/aws/task-execution-trust.json
aws iam attach-role-policy \
  --role-name bitoguard-task-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

**Task Role** (EFS access, CloudWatch):
```bash
aws iam create-role \
  --role-name bitoguard-task-role \
  --assume-role-policy-document file://infra/aws/task-trust.json
aws iam put-role-policy \
  --role-name bitoguard-task-role \
  --policy-name bitoguard-task-policy \
  --policy-document file://infra/aws/task-policy.json
```

## Build and Push Images

```bash
# Authenticate Docker to ECR
aws ecr get-login-password --region ap-northeast-1 | \
  docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com

# Build and push backend
docker build -f bitoguard_core/Dockerfile -t bitoguard-backend .
docker tag bitoguard-backend:latest <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com/bitoguard-backend:latest
docker push <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com/bitoguard-backend:latest

# Build and push frontend
docker build -f bitoguard_frontend/Dockerfile \
  --build-arg BITOGUARD_INTERNAL_API_BASE=http://bitoguard-backend.bitoguard.local:8001 \
  -t bitoguard-frontend .
docker tag bitoguard-frontend:latest <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com/bitoguard-frontend:latest
docker push <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com/bitoguard-frontend:latest
```

Or use the deploy script:

```bash
./scripts/build_and_push.sh <ACCOUNT_ID> ap-northeast-1
```

## ECS Task Definitions

Reference task definition templates are in `infra/aws/`:

- `infra/aws/task-def-backend.json` — Backend task definition
- `infra/aws/task-def-frontend.json` — Frontend task definition

### Backend Task Environment Variables

| Variable | Value |
|----------|-------|
| BITOGUARD_DB_PATH | /mnt/efs/bitoguard.duckdb |
| BITOGUARD_ARTIFACT_DIR | /mnt/efs/artifacts |
| BITOGUARD_SOURCE_URL | https://aws-event-api.bitopro.com |
| BITOGUARD_INTERNAL_API_PORT | 8001 |

### Register Task Definitions

```bash
aws ecs register-task-definition \
  --cli-input-json file://infra/aws/task-def-backend.json \
  --region ap-northeast-1

aws ecs register-task-definition \
  --cli-input-json file://infra/aws/task-def-frontend.json \
  --region ap-northeast-1
```

## ECS Services

### Create Backend Service

```bash
aws ecs create-service \
  --cluster bitoguard \
  --service-name bitoguard-backend \
  --task-definition bitoguard-backend \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-aaa,subnet-bbb],securityGroups=[sg-backend],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=backend,containerPort=8001" \
  --region ap-northeast-1
```

### Create Frontend Service

```bash
aws ecs create-service \
  --cluster bitoguard \
  --service-name bitoguard-frontend \
  --task-definition bitoguard-frontend \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-aaa,subnet-bbb],securityGroups=[sg-frontend],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=frontend,containerPort=3000" \
  --region ap-northeast-1
```

## Scheduled Incremental Refresh

Create an EventBridge Scheduler rule to call `refresh_live` every 15 minutes:

```bash
aws scheduler create-schedule \
  --name bitoguard-refresh-live \
  --schedule-expression "rate(15 minutes)" \
  --target '{"RoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/bitoguard-scheduler-role", "Arn": "arn:aws:ecs:<REGION>:<ACCOUNT_ID>:cluster/bitoguard", "EcsParameters": {"TaskDefinitionArn": "arn:aws:ecs:<REGION>:<ACCOUNT_ID>:task-definition/bitoguard-refresh-live", "LaunchType": "FARGATE", ...}, "Input": "{}"}' \
  --flexible-time-window '{"Mode": "OFF"}' \
  --region ap-northeast-1
```

A separate `bitoguard-refresh-live` task definition should run:
```bash
python pipeline/refresh_live.py
```

## Deployment Script

Use the convenience script for standard deployments:

```bash
./scripts/deploy_aws.sh <ACCOUNT_ID> ap-northeast-1
```

This script:
1. Builds and pushes Docker images
2. Registers new task definitions
3. Updates ECS services
4. Waits for service stability

## Health Checks

```bash
# Backend health
curl https://<ALB_DNS>/api/healthz

# Check ECS service status
aws ecs describe-services \
  --cluster bitoguard \
  --services bitoguard-backend bitoguard-frontend \
  --query 'services[*].{Name:serviceName,Running:runningCount,Desired:desiredCount,Status:status}' \
  --region ap-northeast-1
```

## Log Access

```bash
# Backend logs
aws logs tail /ecs/bitoguard-backend --follow --region ap-northeast-1

# Frontend logs
aws logs tail /ecs/bitoguard-frontend --follow --region ap-northeast-1
```

## Manual Pipeline Trigger (via ECS RunTask)

```bash
# Full sync
aws ecs run-task \
  --cluster bitoguard \
  --task-definition bitoguard-sync \
  --overrides '{"containerOverrides":[{"name":"backend","command":["python","pipeline/sync.py","--full"]}]}' \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-aaa],securityGroups=[sg-backend],assignPublicIp=DISABLED}" \
  --region ap-northeast-1
```

## Cost Estimation

| Component | Config | Monthly Cost (USD) |
|-----------|--------|--------------------|
| ECS Fargate — backend | 1 vCPU × 2 GB, 24/7 | ~$36 |
| ECS Fargate — frontend | 0.5 vCPU × 1 GB, 24/7 | ~$9 |
| ECS Fargate — refresh task | 1 vCPU × 4 GB, 2h/day × 30d | ~$12 |
| EFS Standard | 200 MB (DB + model artifacts) | ~$0.10 |
| Application Load Balancer | Standard | ~$18 |
| ECR | 2 images × ~500 MB | ~$0.10 |
| CloudWatch Logs | 1 GB/day, 30d retention | ~$3 |
| EventBridge Scheduler | 96 invocations/day | ~$0 (free tier) |
| **Total** | | **~$78/month** |

> **Cost reduction tip**: Use Fargate Spot for refresh/train tasks to save 30–60%.

### API Performance Benchmarks

| Endpoint | p50 Latency | p95 Latency | Notes |
|----------|-------------|-------------|-------|
| `GET /healthz` | <5ms | <10ms | No DB access |
| `GET /alerts` (page_size=20) | 15–30ms | 50ms | DuckDB table scan |
| `POST /model/score` | 200–400ms | 800ms | Feature lookup + inference |
| `GET /alerts/{id}/report` | 100–200ms | 400ms | SHAP computation + DB read |
| `POST /pipeline/refresh` (no-op) | <500ms | 1s | Watermark check only |
| `POST /pipeline/refresh` (incremental) | 5–15s | 30s | Feature rebuild for affected users |
| `POST /model/train` | 2–5min | 10min | Full LightGBM + IForest training |

### Throughput Capacity

| Workload | Capacity | Notes |
|----------|----------|-------|
| Concurrent API requests | 20–50 req/s | DuckDB single-writer; reads parallelizable |
| Scoring batch (1,000 users) | ~30s | Feature lookup + inference |
| Incremental refresh | 1,000+ users/15min | Watermark-bounded incremental computation |
| Full historical rebuild | 15–30min | Offline backfill only; not live path |

## Security Considerations

1. Backend is not publicly accessible — only through the ALB via HTTPS
2. EFS access is restricted to the backend security group
3. The BitoPro API is accessed over HTTPS only
4. No sensitive data is logged (IP hashes are used opaquely)
5. All environment variables are passed via ECS task definition (consider AWS Secrets Manager for production)
6. IAM roles follow least-privilege principle
