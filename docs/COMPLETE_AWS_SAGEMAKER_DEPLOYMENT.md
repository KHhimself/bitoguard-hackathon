# Complete AWS + SageMaker Deployment Guide

This guide provides step-by-step instructions for deploying the entire BitoGuard system to AWS with SageMaker integration for ML model training.

## Architecture Overview

The deployment includes:

1. **Application Layer** (ECS Fargate)
   - Backend API (FastAPI)
   - Frontend (Next.js)
   - Shared EFS for DuckDB storage

2. **ML Pipeline** (SageMaker + Step Functions)
   - SageMaker Training Jobs (LightGBM, CatBoost, IsolationForest)
   - SageMaker Processing Jobs (Feature Engineering)
   - Step Functions orchestration
   - Lambda functions for validation and drift detection

3. **Infrastructure** (AWS Managed Services)
   - Application Load Balancer
   - ECR for container images
   - S3 for model artifacts and features
   - EFS for shared database
   - CloudWatch for monitoring
   - SNS for notifications

## Prerequisites

### Required Tools

```bash
# Check AWS CLI
aws --version  # Required: >= 2.0
aws sts get-caller-identity  # Verify credentials

# Check Terraform
terraform --version  # Required: >= 1.0

# Check Docker
docker --version  # Required: >= 20.0

# Check Python
python3 --version  # Required: >= 3.11

# Check jq (for JSON parsing)
jq --version  # Required for deployment scripts
```

### AWS Permissions

Your AWS user/role needs permissions for:
- ECS (Fargate)
- ECR
- S3
- EFS
- ALB
- SageMaker
- Step Functions
- Lambda
- CloudWatch
- SNS
- IAM (role creation)
- SSM Parameter Store

### Cost Estimate

Expected monthly costs:
- ECS Fargate (API): $90-120
- Application Load Balancer: $20
- NAT Gateway (2×): $70
- EFS: $10-20
- S3: $10-30
- SageMaker Training (daily): $50-100
- Lambda + Step Functions: $10-20
- CloudWatch: $10-20

**Total: $270-410/month**

Optimization options available (see Cost Optimization section).

## Quick Start (Automated Deployment)

### Step 1: Clone and Configure

```bash
# Clone repository
git clone <repository-url>
cd bitoguard

# Create Terraform configuration
cd infra/aws/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
aws_region              = "us-east-1"
environment             = "prod"
project_name            = "bitoguard"
ml_notification_email   = "your-email@example.com"
bitopro_api_url         = "https://aws-event-api.bitopro.com"

# Optional: Custom domain
# domain_name           = "bitoguard.example.com"
# certificate_arn       = "arn:aws:acm:..."

# Resource sizing (adjust based on needs)
backend_cpu             = 1024    # 1 vCPU
backend_memory          = 2048    # 2 GB
backend_desired_count   = 2       # Number of tasks

frontend_cpu            = 512     # 0.5 vCPU
frontend_memory         = 1024    # 1 GB
frontend_desired_count  = 2       # Number of tasks
```

### Step 2: Run Automated Deployment

```bash
cd ../../..  # Back to project root
./scripts/deploy-full-aws-sagemaker.sh
```

This script will:
1. Create ECR repositories
2. Build and push Docker images (backend, frontend, training, processing)
3. Package Lambda functions
4. Deploy infrastructure with Terraform
5. Configure SSM parameters
6. Run health checks

**Deployment time: 20-30 minutes**

### Step 3: Verify Deployment

```bash
# Get application URL
cd infra/aws/terraform
terraform output alb_url

# Test backend API
curl http://$(terraform output -raw alb_url)/api/health

# Test frontend
open http://$(terraform output -raw alb_url)
```

### Step 4: Test ML Pipeline

```bash
# Get manual trigger URL
TRIGGER_URL=$(terraform output -raw manual_trigger_function_url)

# Trigger a test run (without training)
curl -X POST "$TRIGGER_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "execution_type": "incremental",
    "skip_training": true
  }'

# Monitor execution
STATE_MACHINE_ARN=$(terraform output -raw ml_pipeline_state_machine_arn)
aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --max-results 5
```

## Manual Deployment (Step-by-Step)

If you prefer to deploy manually or need to troubleshoot:

### 1. Create ECR Repositories

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create repositories
aws ecr create-repository --repository-name bitoguard-backend --region $AWS_REGION
aws ecr create-repository --repository-name bitoguard-frontend --region $AWS_REGION

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

### 2. Build and Push Docker Images

```bash
ECR_REGISTRY="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Backend API
cd bitoguard_core
docker build -f Dockerfile -t bitoguard-backend:latest .
docker tag bitoguard-backend:latest $ECR_REGISTRY/bitoguard-backend:latest
docker push $ECR_REGISTRY/bitoguard-backend:latest

# Training image
docker build -f Dockerfile.training -t bitoguard-training:latest .
docker tag bitoguard-training:latest $ECR_REGISTRY/bitoguard-backend:training
docker push $ECR_REGISTRY/bitoguard-backend:training

# Processing image
docker build -f Dockerfile.processing -t bitoguard-processing:latest .
docker tag bitoguard-processing:latest $ECR_REGISTRY/bitoguard-backend:processing
docker push $ECR_REGISTRY/bitoguard-backend:processing

# Frontend
cd ../bitoguard_frontend
docker build -t bitoguard-frontend:latest .
docker tag bitoguard-frontend:latest $ECR_REGISTRY/bitoguard-frontend:latest
docker push $ECR_REGISTRY/bitoguard-frontend:latest
```

### 3. Package Lambda Functions

```bash
cd ../infra/aws/lambda

# Package each Lambda function
for lambda in drift_detector config_validator manual_trigger model_registry tuning_analyzer; do
  echo "Packaging $lambda..."
  cd $lambda
  
  # Create temp directory
  temp_dir=$(mktemp -d)
  cp lambda_function.py $temp_dir/
  
  # Install dependencies if needed
  if [ -f requirements.txt ]; then
    pip3 install -r requirements.txt -t $temp_dir/ --quiet
  fi
  
  # Create zip
  cd $temp_dir
  zip -r ../${lambda}.zip . >/dev/null
  cd ..
  
  # Cleanup
  rm -rf $temp_dir
  cd ..
done
```

### 4. Deploy Infrastructure

```bash
cd ../terraform

# Initialize Terraform
terraform init

# Plan deployment
terraform plan -out=tfplan

# Review plan and apply
terraform apply tfplan
```

### 5. Configure SSM Parameters

```bash
# Get outputs
ARTIFACTS_BUCKET=$(terraform output -raw ml_artifacts_bucket)
EFS_ID=$(terraform output -raw efs_file_system_id)

# S3 and EFS
aws ssm put-parameter --name /bitoguard/ml-pipeline/s3/artifacts_bucket \
  --value "$ARTIFACTS_BUCKET" --type String --overwrite

aws ssm put-parameter --name /bitoguard/ml-pipeline/efs/file_system_id \
  --value "$EFS_ID" --type String --overwrite

# Training hyperparameters - LightGBM
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/n_estimators \
  --value "500" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/learning_rate \
  --value "0.05" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/max_depth \
  --value "7" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/num_leaves \
  --value "63" --type String --overwrite

# Training hyperparameters - CatBoost
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/iterations \
  --value "500" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/learning_rate \
  --value "0.05" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/depth \
  --value "6" --type String --overwrite

# Training hyperparameters - IsolationForest
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/iforest/n_estimators \
  --value "200" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/iforest/contamination \
  --value "0.1" --type String --overwrite

# Thresholds
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/feature_drift_kl \
  --value "0.1" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/prediction_drift_percentage \
  --value "0.15" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/alert_risk_score \
  --value "0.7" --type String --overwrite

# Resource configurations
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/sagemaker_instance_type \
  --value "ml.m5.xlarge" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/sagemaker_max_runtime_seconds \
  --value "3600" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/ecs_task_cpu \
  --value "2048" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/ecs_task_memory \
  --value "4096" --type String --overwrite

# Schedules
aws ssm put-parameter --name /bitoguard/ml-pipeline/scheduling/daily_full_pipeline_cron \
  --value "cron(0 2 * * ? *)" --type String --overwrite
aws ssm put-parameter --name /bitoguard/ml-pipeline/scheduling/incremental_refresh_cron \
  --value "cron(0 8,12,16,20 * * ? *)" --type String --overwrite
```

## Training Models on SageMaker

### Initial Training Run

```bash
# Get manual trigger URL
TRIGGER_URL=$(terraform output -raw manual_trigger_function_url)

# Trigger full pipeline with training
curl -X POST "$TRIGGER_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "execution_type": "full",
    "skip_training": false,
    "model_types": ["lgbm", "catboost", "iforest"]
  }'
```

### Monitor Training

```bash
# Watch Step Functions execution
STATE_MACHINE_ARN=$(terraform output -raw ml_pipeline_state_machine_arn)
aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --max-results 5

# Get execution details
EXECUTION_ARN="<execution-arn-from-above>"
aws stepfunctions describe-execution --execution-arn "$EXECUTION_ARN"

# Watch SageMaker training jobs
aws sagemaker list-training-jobs \
  --sort-by CreationTime \
  --sort-order Descending \
  --max-results 5

# View training job details
TRAINING_JOB_NAME="<job-name-from-above>"
aws sagemaker describe-training-job --training-job-name "$TRAINING_JOB_NAME"

# View training logs
aws logs tail /aws/sagemaker/TrainingJobs --follow \
  --filter-pattern "$TRAINING_JOB_NAME"

# View ECS task logs
aws logs tail /ecs/bitoguard-prod-ml-pipeline --follow
```

### Check Training Results

```bash
# List models in S3
ARTIFACTS_BUCKET=$(terraform output -raw ml_artifacts_bucket)
aws s3 ls s3://$ARTIFACTS_BUCKET/models/ --recursive

# Download validation report
aws s3 cp s3://$ARTIFACTS_BUCKET/models/validation_report.json .
cat validation_report.json | jq .

# Download model artifacts
aws s3 cp s3://$ARTIFACTS_BUCKET/models/lgbm_latest.joblib .
aws s3 cp s3://$ARTIFACTS_BUCKET/models/catboost_latest.joblib .
aws s3 cp s3://$ARTIFACTS_BUCKET/models/iforest_latest.json .
```

## Monitoring and Operations

### CloudWatch Dashboard

```bash
DASHBOARD_NAME=$(terraform output -raw ml_pipeline_dashboard_name)
echo "Dashboard URL: https://console.aws.amazon.com/cloudwatch/home?region=$AWS_REGION#dashboards:name=$DASHBOARD_NAME"
```

The dashboard shows:
- Pipeline execution metrics
- Training job status
- Feature drift alerts
- Prediction drift alerts
- ECS task health
- API response times

### CloudWatch Logs

```bash
# Backend API logs
aws logs tail /ecs/bitoguard-prod-backend --follow

# Frontend logs
aws logs tail /ecs/bitoguard-prod-frontend --follow

# ML pipeline logs
aws logs tail /ecs/bitoguard-prod-ml-pipeline --follow

# Lambda function logs
aws logs tail /aws/lambda/bitoguard-prod-drift-detector --follow
aws logs tail /aws/lambda/bitoguard-prod-config-validator --follow
```

### SNS Notifications

Subscribe to SNS topics for alerts:

```bash
# Get SNS topic ARNs
terraform output sns_topic_arns

# Subscribe to notifications
aws sns subscribe \
  --topic-arn "arn:aws:sns:$AWS_REGION:$AWS_ACCOUNT_ID:bitoguard-prod-ml-pipeline-notifications" \
  --protocol email \
  --notification-endpoint your-email@example.com

# Subscribe to drift alerts
aws sns subscribe \
  --topic-arn "arn:aws:sns:$AWS_REGION:$AWS_ACCOUNT_ID:bitoguard-prod-drift-alerts" \
  --protocol email \
  --notification-endpoint your-email@example.com
```

### CloudWatch Alarms

Configured alarms:
- Pipeline execution failure
- Pipeline duration > 2 hours
- Feature drift count > 5
- Prediction drift > 15%
- Backend CPU > 80%
- Backend memory > 80%
- Unhealthy target count > 0

## Scheduled Execution

The pipeline runs automatically:

1. **Daily Full Pipeline** (2 AM UTC)
   - Data sync
   - Feature engineering
   - Model training on SageMaker
   - Scoring
   - Drift detection

2. **Incremental Refresh** (Every 4 hours: 8 AM, 12 PM, 4 PM, 8 PM UTC)
   - Data sync (new records only)
   - Scoring with existing models
   - Alert generation

To modify schedules:

```bash
# Change daily pipeline time
aws ssm put-parameter \
  --name /bitoguard/ml-pipeline/scheduling/daily_full_pipeline_cron \
  --value "cron(0 3 * * ? *)" \
  --type String \
  --overwrite

# Change incremental refresh frequency
aws ssm put-parameter \
  --name /bitoguard/ml-pipeline/scheduling/incremental_refresh_cron \
  --value "cron(0 */6 * * ? *)" \
  --type String \
  --overwrite
```

## Troubleshooting

### Pipeline Execution Fails

1. Check Step Functions execution history:
   ```bash
   aws stepfunctions describe-execution --execution-arn "$EXECUTION_ARN"
   ```

2. Check CloudWatch logs for errors:
   ```bash
   aws logs tail /ecs/bitoguard-prod-ml-pipeline --follow
   ```

3. Verify SSM parameters are configured:
   ```bash
   aws ssm get-parameters-by-path --path /bitoguard/ml-pipeline --recursive
   ```

### SageMaker Training Fails

1. Check training job status:
   ```bash
   aws sagemaker describe-training-job --training-job-name "$TRAINING_JOB_NAME"
   ```

2. View training logs:
   ```bash
   aws logs tail /aws/sagemaker/TrainingJobs --follow --filter-pattern "$TRAINING_JOB_NAME"
   ```

3. Common issues:
   - Insufficient training data in S3
   - Invalid hyperparameters
   - Instance type not available
   - IAM permission issues

### ECS Tasks Not Starting

1. Check ECS service events:
   ```bash
   aws ecs describe-services \
     --cluster bitoguard-prod \
     --services bitoguard-prod-backend
   ```

2. Check task failures:
   ```bash
   aws ecs list-tasks \
     --cluster bitoguard-prod \
     --desired-status STOPPED
   ```

3. Common issues:
   - ECR image not found
   - EFS mount failure
   - Security group blocking traffic
   - Insufficient CPU/memory

### API Health Check Fails

1. Check ALB target health:
   ```bash
   aws elbv2 describe-target-health \
     --target-group-arn "$(terraform output -raw backend_target_group_arn)"
   ```

2. Check backend logs:
   ```bash
   aws logs tail /ecs/bitoguard-prod-backend --follow
   ```

3. Test API directly:
   ```bash
   curl -v http://$(terraform output -raw alb_url)/api/health
   ```

## Cost Optimization

### Development Environment ($80-120/month)

```hcl
# terraform.tfvars
environment             = "dev"
backend_desired_count   = 1
frontend_desired_count  = 1
backend_cpu             = 512
backend_memory          = 1024
frontend_cpu            = 256
frontend_memory         = 512
enable_nat_gateway      = false  # Use NAT instance instead
```

### Use Spot Instances

```hcl
# terraform.tfvars
use_fargate_spot        = true
sagemaker_use_spot      = true
sagemaker_max_wait_time = 3600
```

### Reduce Log Retention

```bash
aws ssm put-parameter \
  --name /bitoguard/ml-pipeline/logging/retention_days \
  --value "3" \
  --type String \
  --overwrite
```

### Use S3 Lifecycle Policies

Models are automatically archived to Glacier after 90 days (configured in Terraform).

## Security Best Practices

1. **Enable HTTPS**: Add ACM certificate and configure HTTPS listener
2. **Restrict Security Groups**: Limit inbound traffic to specific IPs
3. **Enable VPC Flow Logs**: Monitor network traffic
4. **Use Secrets Manager**: Store API keys securely
5. **Enable CloudTrail**: Audit API calls
6. **Enable GuardDuty**: Threat detection
7. **Regular Updates**: Keep Docker images updated

## Backup and Disaster Recovery

### EFS Backup

```bash
# Create backup
aws backup start-backup-job \
  --backup-vault-name bitoguard-backup-vault \
  --resource-arn "arn:aws:elasticfilesystem:$AWS_REGION:$AWS_ACCOUNT_ID:file-system/$EFS_ID"

# List backups
aws backup list-recovery-points-by-resource \
  --resource-arn "arn:aws:elasticfilesystem:$AWS_REGION:$AWS_ACCOUNT_ID:file-system/$EFS_ID"
```

### S3 Versioning

S3 buckets have versioning enabled. To restore a previous version:

```bash
aws s3api list-object-versions \
  --bucket $ARTIFACTS_BUCKET \
  --prefix models/

aws s3api get-object \
  --bucket $ARTIFACTS_BUCKET \
  --key models/lgbm_latest.joblib \
  --version-id <version-id> \
  lgbm_restored.joblib
```

### Terraform State Backup

```bash
# Export current state
terraform state pull > terraform.tfstate.backup

# Store in S3
aws s3 cp terraform.tfstate.backup s3://your-backup-bucket/
```

## Cleanup

To remove all resources:

```bash
cd infra/aws/terraform

# Destroy infrastructure
terraform destroy

# Delete ECR images
aws ecr delete-repository --repository-name bitoguard-backend --force
aws ecr delete-repository --repository-name bitoguard-frontend --force

# Delete Lambda packages
rm -f ../lambda/*.zip
```

## Next Steps

1. ✅ Configure custom domain with Route53
2. ✅ Enable HTTPS with ACM certificate
3. ✅ Set up CloudFront for frontend CDN
4. ✅ Configure WAF rules
5. ✅ Enable automated backups
6. ✅ Set up multi-region deployment
7. ✅ Implement CI/CD pipeline
8. ✅ Load test the system

## Support

For issues or questions:
- Check CloudWatch Logs for detailed errors
- Review Terraform state for resource configuration
- Consult AWS documentation for service-specific issues
- Open an issue in the repository

## Summary

You now have a complete, production-ready deployment of BitoGuard on AWS with:

- ✅ Scalable application infrastructure (ECS Fargate)
- ✅ Automated ML pipeline (SageMaker + Step Functions)
- ✅ Comprehensive monitoring (CloudWatch)
- ✅ Automated training and scoring
- ✅ Drift detection and alerting
- ✅ High availability and auto-scaling
- ✅ Security best practices
- ✅ Cost optimization options

The system is ready to detect fraud and AML risks in production!
