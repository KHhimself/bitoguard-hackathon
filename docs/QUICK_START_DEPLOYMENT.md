# Quick Start: Deploy & Train on AWS

This guide walks you through deploying BitoGuard's ML pipeline to AWS and training models with SageMaker.

## Prerequisites Check

Run these commands to verify you have everything:

```bash
# Check AWS CLI
aws --version
aws sts get-caller-identity

# Check Terraform
terraform --version

# Check Docker
docker --version

# Check Python
python3 --version
```

## Step 1: Prepare Configuration

Create Terraform variables file:

```bash
cd infra/aws/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your settings:

```hcl
aws_region           = "us-east-1"
environment          = "prod"
project_name         = "bitoguard"
ml_notification_email = "your-email@example.com"
bitopro_api_url      = "https://aws-event-api.bitopro.com"
```

## Step 2: Package Lambda Functions

```bash
cd infra/aws/lambda

# Package drift detector
cd drift_detector
pip install -r requirements.txt -t .
zip -r ../drift_detector.zip .
cd ..

# Package config validator
cd config_validator
pip install -r requirements.txt -t .
zip -r ../config_validator.zip .
cd ..

# Package manual trigger
cd manual_trigger
pip install -r requirements.txt -t .
zip -r ../manual_trigger.zip .
cd ..
```

## Step 3: Build Training Docker Image

```bash
cd bitoguard_core

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1
ECR_REGISTRY="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Create ECR repository (if doesn't exist)
aws ecr create-repository --repository-name bitoguard-backend --region $AWS_REGION || true

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY

# Build and push training image
docker build -f Dockerfile.training -t bitoguard-training:latest .
docker tag bitoguard-training:latest $ECR_REGISTRY/bitoguard-backend:training
docker push $ECR_REGISTRY/bitoguard-backend:training
```

## Step 4: Deploy Infrastructure with Terraform

```bash
cd infra/aws/terraform

# Initialize Terraform
terraform init

# Plan deployment
terraform plan -out=tfplan

# Apply (this will create all AWS resources)
terraform apply tfplan
```

This creates:
- S3 buckets for models and features
- EFS for shared DuckDB storage
- ECS task definitions
- Lambda functions
- Step Functions state machine
- EventBridge schedules
- CloudWatch dashboards and alarms
- IAM roles and policies

## Step 5: Configure SSM Parameters

```bash
# Set training hyperparameters
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/n_estimators --value "500" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/learning_rate --value "0.05" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/max_depth --value "7" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/num_leaves --value "63" --type String --overwrite

aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/iterations --value "500" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/learning_rate --value "0.05" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/depth --value "6" --type String --overwrite

aws ssm put-parameter --name /bitoguard/ml-pipeline/training/iforest/n_estimators --value "200" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/iforest/contamination --value "0.1" --type String --overwrite

# Set thresholds
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/feature_drift_kl --value "0.1" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/prediction_drift_percentage --value "0.15" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/alert_risk_score --value "0.7" --type String --overwrite

# Set resource configs
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/sagemaker_instance_type --value "ml.m5.xlarge" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/sagemaker_max_runtime_seconds --value "3600" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/ecs_task_cpu --value "2048" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/ecs_task_memory --value "4096" --type String --overwrite

# Set S3 bucket
ARTIFACTS_BUCKET=$(terraform output -raw ml_artifacts_bucket)
aws ssm put-parameter --name /bitoguard/ml-pipeline/s3/artifacts_bucket --value "$ARTIFACTS_BUCKET" --type String --overwrite

# Set EFS
EFS_ID=$(terraform output -raw efs_file_system_id)
aws ssm put-parameter --name /bitoguard/ml-pipeline/efs/file_system_id --value "$EFS_ID" --type String --overwrite

# Set schedules
aws ssm put-parameter --name /bitoguard/ml-pipeline/scheduling/daily_full_pipeline_cron --value "cron(0 2 * * ? *)" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/scheduling/incremental_refresh_cron --value "cron(0 8,12,16,20 * * ? *)" --type String --overwrite
```

## Step 6: Prepare Training Data

First, sync data and build features locally, then upload to S3:

```bash
cd bitoguard_core

# Activate virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set environment
export PYTHONPATH=.
export AWS_REGION=us-east-1
export BITOGUARD_ML_ARTIFACTS_BUCKET=$(cd ../infra/aws/terraform && terraform output -raw ml_artifacts_bucket)

# Sync data
python -m pipeline.sync

# Build features and export to S3
python -c "
from features.build_features_v2 import build_v2
from features.registry import build_and_store_v2_features
from db.store import DuckDBStore
from config import load_settings
import os

settings = load_settings()
store = DuckDBStore(settings.db_path)

users = store.read_table('canonical.users')
fiat = store.read_table('canonical.fiat_transactions')
crypto = store.read_table('canonical.crypto_transactions')
trades = store.read_table('canonical.trade_orders')
logins = store.read_table('canonical.login_events')
edges = store.read_table('canonical.entity_edges')

# Build and export to S3
result = build_and_store_v2_features(
    users, fiat, crypto, trades, logins, edges,
    store=store,
    export_to_s3=True
)
print(f'Features exported: {len(result)} users, {len(result.columns)} features')
"
```

## Step 7: Trigger Training on SageMaker

Now trigger the ML pipeline to train models on SageMaker:

```bash
# Get manual trigger URL
TRIGGER_URL=$(cd infra/aws/terraform && terraform output -raw manual_trigger_function_url)

# Trigger full pipeline with training
curl -X POST "$TRIGGER_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "execution_type": "full",
    "skip_training": false,
    "model_types": ["lgbm", "catboost", "iforest"]
  }'
```

## Step 8: Monitor Training

Watch the training progress:

```bash
# Get state machine ARN
STATE_MACHINE_ARN=$(cd infra/aws/terraform && terraform output -raw ml_pipeline_state_machine_arn)

# List recent executions
aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --max-results 5

# Get execution details (replace with actual execution ARN)
aws stepfunctions describe-execution \
  --execution-arn "arn:aws:states:us-east-1:ACCOUNT:execution:bitoguard-prod-ml-pipeline:EXECUTION_ID"

# Watch SageMaker training jobs
aws sagemaker list-training-jobs \
  --sort-by CreationTime \
  --sort-order Descending \
  --max-results 5

# View CloudWatch logs
aws logs tail /ecs/bitoguard-prod-ml-pipeline --follow
```

## Step 9: Check Training Results

After training completes (15-30 minutes):

```bash
# List trained models in S3
aws s3 ls s3://$BITOGUARD_ML_ARTIFACTS_BUCKET/models/ --recursive

# Download validation report
aws s3 cp s3://$BITOGUARD_ML_ARTIFACTS_BUCKET/models/validation_report.json .
cat validation_report.json | jq .
```

## Step 10: View Dashboard

Open CloudWatch dashboard:

```bash
DASHBOARD_NAME=$(cd infra/aws/terraform && terraform output -raw ml_pipeline_dashboard_name)
echo "Dashboard URL: https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=$DASHBOARD_NAME"
```

## Troubleshooting

### Training Job Fails

```bash
# Get training job name from Step Functions execution
TRAINING_JOB_NAME="bitoguard-lgbm-EXECUTION_ID"

# View training job details
aws sagemaker describe-training-job --training-job-name "$TRAINING_JOB_NAME"

# View training logs
aws logs tail /aws/sagemaker/TrainingJobs --follow --filter-pattern "$TRAINING_JOB_NAME"
```

### Lambda Function Errors

```bash
# View drift detector logs
aws logs tail /aws/lambda/bitoguard-prod-drift-detector --follow

# View config validator logs
aws logs tail /aws/lambda/bitoguard-prod-config-validator --follow
```

### ECS Task Failures

```bash
# List recent task failures
aws ecs list-tasks \
  --cluster bitoguard-prod \
  --desired-status STOPPED \
  --max-results 5

# Get task details
aws ecs describe-tasks \
  --cluster bitoguard-prod \
  --tasks TASK_ARN
```

## Cost Estimate

Expected monthly costs:
- SageMaker training (daily): $50-100
- ECS Fargate tasks: $30-50
- S3 storage: $10-20
- Lambda executions: $5-10
- CloudWatch logs: $10-20
- EFS storage: $10-20

Total: ~$115-220/month

Use Spot instances to reduce by 30-70%.

## Next Steps

1. Subscribe to SNS topics for alerts
2. Review first training results
3. Adjust hyperparameters in SSM if needed
4. Set up automated daily runs (already configured)
5. Monitor drift detection alerts

## Clean Up

To remove all resources:

```bash
cd infra/aws/terraform
terraform destroy
```
