# SageMaker Deployment Guide

## Overview

This guide covers deploying and operating the BitoGuard ML Pipeline with AWS SageMaker integration. The system provides automated ML operations including data preprocessing, model training, hyperparameter tuning, model registry, and monitoring.

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform >= 1.0
- Docker installed for building container images
- Python 3.11 for local testing
- Access to AWS account with permissions for SageMaker, S3, ECS, Lambda, Step Functions

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    EventBridge Scheduler                         │
│  Daily Full Run (2 AM UTC) | Incremental Refresh (4 hours)     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│              Step Functions State Machine                        │
│  ValidateConfig → DataSync → Preprocessing → Training/Tuning    │
│  → ModelRegistry → Scoring → DriftDetection → Notifications     │
└─────────────────────────────────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ ECS Fargate  │ │  SageMaker   │ │   Lambda     │
│ - Data Sync  │ │ - Processing │ │ - Drift      │
│ - Features   │ │ - Training   │ │ - Config     │
│ - Scoring    │ │ - Tuning     │ │ - Registry   │
└──────────────┘ └──────────────┘ └──────────────┘
        │            │            │
        └────────────┼────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Storage & Monitoring                          │
│  S3 (artifacts) | EFS (DuckDB) | CloudWatch (logs/metrics)     │
└─────────────────────────────────────────────────────────────────┘
```

## Deployment Steps

### 1. Build and Push Docker Images

Build the three SageMaker container images:

```bash
# Navigate to project root
cd /path/to/bitoguard

# Build processing container
docker build -f bitoguard_core/Dockerfile.processing \
  -t bitoguard-processing:latest \
  bitoguard_core/

# Build training container
docker build -f bitoguard_core/Dockerfile.training \
  -t bitoguard-training:latest \
  bitoguard_core/

# Tag and push to ECR
AWS_REGION=us-west-2
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/bitoguard

# Authenticate Docker to ECR
aws ecr get-login-password --region ${AWS_REGION} | \
  docker login --username AWS --password-stdin ${ECR_REPO}

# Tag and push processing image
docker tag bitoguard-processing:latest ${ECR_REPO}:processing
docker push ${ECR_REPO}:processing

# Tag and push training image
docker tag bitoguard-training:latest ${ECR_REPO}:training
docker push ${ECR_REPO}:training
```

### 2. Package Lambda Functions

Package the Lambda functions for deployment:

```bash
cd infra/aws/lambda

# Package drift detector
cd drift_detector
zip -r ../drift_detector.zip lambda_function.py
cd ..

# Package config validator
cd config_validator
zip -r ../config_validator.zip lambda_function.py
cd ..

# Package manual trigger
cd manual_trigger
zip -r ../manual_trigger.zip lambda_function.py
cd ..

# Tuning analyzer and model registry are auto-packaged by Terraform
```

### 3. Configure Terraform Variables

Create `terraform.tfvars` in `infra/aws/terraform/`:

```hcl
aws_region = "us-west-2"
environment = "prod"
project_name = "bitoguard"

# VPC Configuration
vpc_cidr = "10.0.0.0/16"
availability_zones = ["us-west-2a", "us-west-2b"]

# ECS Configuration
backend_cpu = 1024
backend_memory = 2048
backend_desired_count = 2

# ML Pipeline Configuration
ml_pipeline_schedule_enabled = true
ml_pipeline_daily_schedule = "cron(0 2 * * ? *)"  # 2 AM UTC daily
ml_pipeline_incremental_schedule = "cron(0 8,12,16,20 * * ? *)"  # Every 4 hours

# SageMaker Configuration
sagemaker_processing_instance_type = "ml.m5.xlarge"
sagemaker_training_instance_type = "ml.m5.xlarge"
sagemaker_enable_spot_instances = true

# Tags
common_tags = {
  Project     = "BitoGuard"
  Environment = "Production"
  ManagedBy   = "Terraform"
}
```

### 4. Deploy Infrastructure

```bash
cd infra/aws/terraform

# Initialize Terraform
terraform init

# Review planned changes
terraform plan

# Apply infrastructure
terraform apply

# Save important outputs
terraform output > outputs.txt
```

### 5. Configure SSM Parameters

Set up configuration parameters in AWS Systems Manager Parameter Store:

```bash
# Training hyperparameters
aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/training/lgbm/n_estimators" \
  --value "250" \
  --type "String"

aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/training/lgbm/learning_rate" \
  --value "0.05" \
  --type "String"

aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/training/lgbm/num_leaves" \
  --value "31" \
  --type "String"

# Drift detection thresholds
aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/drift/kl_divergence_threshold" \
  --value "0.1" \
  --type "String"

aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/drift/prediction_drift_threshold" \
  --value "0.15" \
  --type "String"

# Alert thresholds
aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/scoring/alert_threshold" \
  --value "0.7" \
  --type "String"

# Scheduling configuration
aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/schedule/enable_tuning" \
  --value "false" \
  --type "String"

aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/schedule/skip_training" \
  --value "false" \
  --type "String"
```

### 6. Upload Initial Data to EFS

Mount EFS and upload initial DuckDB database:

```bash
# Create mount point
sudo mkdir -p /mnt/efs

# Mount EFS (replace with your EFS ID from Terraform output)
EFS_ID=$(terraform output -raw efs_id)
sudo mount -t efs ${EFS_ID}:/ /mnt/efs

# Copy DuckDB database
sudo cp bitoguard_core/artifacts/bitoguard.duckdb /mnt/efs/

# Set permissions
sudo chmod 666 /mnt/efs/bitoguard.duckdb
```

### 7. Verify Deployment

Check that all components are deployed:

```bash
# Check Step Functions state machine
aws stepfunctions list-state-machines \
  --query "stateMachines[?contains(name, 'bitoguard')].{Name:name,Status:status}"

# Check Lambda functions
aws lambda list-functions \
  --query "Functions[?contains(FunctionName, 'bitoguard')].{Name:FunctionName,Runtime:Runtime}"

# Check SageMaker model package groups
aws sagemaker list-model-package-groups \
  --name-contains bitoguard

# Check EventBridge rules
aws events list-rules \
  --name-prefix bitoguard

# Check CloudWatch dashboard
aws cloudwatch list-dashboards \
  --dashboard-name-prefix bitoguard
```

## Operating the ML Pipeline

### Manual Execution

Trigger a manual pipeline execution:

```bash
# Using AWS CLI
aws stepfunctions start-execution \
  --state-machine-arn $(terraform output -raw ml_pipeline_state_machine_arn) \
  --name "manual-$(date +%Y%m%d-%H%M%S)" \
  --input '{
    "executionType": "full",
    "syncCommand": ["python", "-m", "pipeline.sync", "--full"],
    "enable_tuning": false,
    "skip_training": false
  }'

# Using Lambda function URL
FUNCTION_URL=$(terraform output -raw manual_trigger_function_url)
aws lambda invoke-url \
  --function-url ${FUNCTION_URL} \
  --payload '{"executionType": "full"}' \
  response.json
```

### Monitoring Execution

Monitor pipeline execution in real-time:

```bash
# Get latest execution ARN
EXECUTION_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn $(terraform output -raw ml_pipeline_state_machine_arn) \
  --max-results 1 \
  --query "executions[0].executionArn" \
  --output text)

# Check execution status
aws stepfunctions describe-execution \
  --execution-arn ${EXECUTION_ARN}

# View CloudWatch logs
aws logs tail /aws/stepfunctions/bitoguard-prod-ml-pipeline --follow

# View SageMaker training job logs
aws logs tail /aws/sagemaker/TrainingJobs --follow
```

### Viewing Results

Access pipeline results:

```bash
# List trained models in S3
aws s3 ls s3://bitoguard-prod-ml-artifacts/models/ --recursive

# List feature snapshots
aws s3 ls s3://bitoguard-prod-ml-artifacts/features/processed/

# List drift reports
aws s3 ls s3://bitoguard-prod-ml-artifacts/drift-reports/

# View CloudWatch dashboard
echo "https://console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}#dashboards:name=bitoguard-prod-ml-pipeline"
```

## SageMaker Processing Jobs

### Configuration

Processing jobs run data preprocessing and feature engineering:

- **Instance Type**: ml.m5.xlarge (4 vCPU, 16GB RAM)
- **Container**: `bitoguard-processing:latest`
- **Input**: Raw data from EFS or S3
- **Output**: Processed features in Parquet format, data quality reports

### Customization

Modify processing job parameters in Step Functions state machine:

```json
{
  "ProcessingResources": {
    "ClusterConfig": {
      "InstanceType": "ml.m5.xlarge",
      "InstanceCount": 1,
      "VolumeSizeInGB": 30
    }
  },
  "Environment": {
    "DATA_SOURCE": "efs",
    "FEATURE_STORE_BUCKET": "bitoguard-prod-ml-artifacts",
    "SNAPSHOT_ID": "$.Execution.Name"
  }
}
```

### Monitoring

View processing job metrics:

```bash
# List recent processing jobs
aws sagemaker list-processing-jobs \
  --name-contains bitoguard \
  --max-results 10

# Describe specific job
aws sagemaker describe-processing-job \
  --processing-job-name bitoguard-preprocessing-20260315-120000

# View logs
aws logs tail /aws/sagemaker/ProcessingJobs --follow
```

## SageMaker Training Jobs

### Configuration

Training jobs train LightGBM, CatBoost, and IsolationForest models:

- **Instance Types**: 
  - LightGBM/CatBoost: ml.m5.xlarge (4 vCPU, 16GB RAM)
  - IsolationForest: ml.m5.large (2 vCPU, 8GB RAM)
- **Spot Instances**: Enabled (up to 70% cost savings)
- **Container**: `bitoguard-training:latest`
- **Parallel Training**: All three models train simultaneously

### Hyperparameter Configuration

Update hyperparameters via SSM Parameter Store:

```bash
# LightGBM parameters
aws ssm put-parameter --name "/bitoguard/ml-pipeline/training/lgbm/n_estimators" --value "300" --overwrite
aws ssm put-parameter --name "/bitoguard/ml-pipeline/training/lgbm/learning_rate" --value "0.03" --overwrite

# CatBoost parameters
aws ssm put-parameter --name "/bitoguard/ml-pipeline/training/catboost/iterations" --value "500" --overwrite
aws ssm put-parameter --name "/bitoguard/ml-pipeline/training/catboost/learning_rate" --value "0.05" --overwrite
```

### Monitoring

Track training progress:

```bash
# List training jobs
aws sagemaker list-training-jobs \
  --name-contains bitoguard \
  --max-results 10

# Get training metrics
aws sagemaker describe-training-job \
  --training-job-name bitoguard-lgbm-20260315-120000 \
  --query "FinalMetricDataList"

# View logs
aws logs tail /aws/sagemaker/TrainingJobs --follow
```

## Hyperparameter Tuning

### Enabling Tuning

Enable hyperparameter tuning in pipeline execution:

```bash
aws stepfunctions start-execution \
  --state-machine-arn $(terraform output -raw ml_pipeline_state_machine_arn) \
  --input '{
    "executionType": "full",
    "enable_tuning": true,
    "skip_training": false
  }'
```

### Tuning Configuration

Tuning uses Bayesian optimization to find optimal hyperparameters:

- **Strategy**: Bayesian
- **Objective Metric**: precision_at_100 (maximize)
- **Max Training Jobs**: 20
- **Max Parallel Jobs**: 3
- **Parameter Ranges**: Defined in `step_functions.tf`

### Monitoring Tuning Jobs

```bash
# List tuning jobs
aws sagemaker list-hyper-parameter-tuning-jobs \
  --name-contains bitoguard

# Describe tuning job
aws sagemaker describe-hyper-parameter-tuning-job \
  --hyper-parameter-tuning-job-name bitoguard-lgbm-tuning-20260315-120000

# Get best training job
aws sagemaker describe-hyper-parameter-tuning-job \
  --hyper-parameter-tuning-job-name bitoguard-lgbm-tuning-20260315-120000 \
  --query "BestTrainingJob"

# View tuning analysis results in S3
aws s3 ls s3://bitoguard-prod-ml-artifacts/tuning-analysis/
```

## Model Registry

### Model Registration

Models are automatically registered after training:

1. Training job completes
2. `model-registry` Lambda extracts metadata
3. Model package created in SageMaker Model Registry
4. Approval status set to `PendingManualApproval`

### Approving Models

Approve models for deployment:

```bash
# List model packages
aws sagemaker list-model-packages \
  --model-package-group-name bitoguard-prod-lgbm

# Get latest model package ARN
MODEL_PACKAGE_ARN=$(aws sagemaker list-model-packages \
  --model-package-group-name bitoguard-prod-lgbm \
  --max-results 1 \
  --sort-by CreationTime \
  --sort-order Descending \
  --query "ModelPackageSummaryList[0].ModelPackageArn" \
  --output text)

# Approve model
aws sagemaker update-model-package \
  --model-package-arn ${MODEL_PACKAGE_ARN} \
  --model-approval-status Approved

# Reject model
aws sagemaker update-model-package \
  --model-package-arn ${MODEL_PACKAGE_ARN} \
  --model-approval-status Rejected \
  --approval-description "Model performance below threshold"
```

### Model Lineage

Track model lineage and metadata:

```bash
# Describe model package
aws sagemaker describe-model-package \
  --model-package-name ${MODEL_PACKAGE_ARN}

# View model metadata in S3
aws s3 cp s3://bitoguard-prod-ml-artifacts/model-registry/lgbm/latest.json -
```

## Drift Detection

### Configuration

Drift detection runs after scoring:

- **Feature Drift**: KL divergence for numerical features, chi-square for categorical
- **Prediction Drift**: Distribution comparison between runs
- **Thresholds**: Configurable via SSM Parameter Store

### Viewing Drift Reports

```bash
# List drift reports
aws s3 ls s3://bitoguard-prod-ml-artifacts/drift-reports/

# Download latest report
aws s3 cp s3://bitoguard-prod-ml-artifacts/drift-reports/drift_$(date +%Y%m%d).json -

# View drift metrics in CloudWatch
aws cloudwatch get-metric-statistics \
  --namespace BitoGuard/MLPipeline \
  --metric-name FeatureDriftCount \
  --start-time $(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Sum
```

## Troubleshooting

### Pipeline Execution Failures

Check execution history:

```bash
# List failed executions
aws stepfunctions list-executions \
  --state-machine-arn $(terraform output -raw ml_pipeline_state_machine_arn) \
  --status-filter FAILED

# Get failure details
aws stepfunctions describe-execution \
  --execution-arn <EXECUTION_ARN> \
  --query "cause"

# View error logs
aws logs filter-log-events \
  --log-group-name /aws/stepfunctions/bitoguard-prod-ml-pipeline \
  --filter-pattern "ERROR"
```

### SageMaker Job Failures

Debug SageMaker job failures:

```bash
# Get failure reason
aws sagemaker describe-training-job \
  --training-job-name <JOB_NAME> \
  --query "FailureReason"

# View job logs
aws logs get-log-events \
  --log-group-name /aws/sagemaker/TrainingJobs \
  --log-stream-name <JOB_NAME>/algo-1-<TIMESTAMP>
```

### Common Issues

1. **Spot Instance Interruption**: Training jobs automatically retry with on-demand instances
2. **EFS Mount Failures**: Check security group rules and EFS mount targets
3. **S3 Permission Errors**: Verify IAM roles have correct S3 bucket permissions
4. **Lambda Timeout**: Increase timeout in `lambda.tf` if processing takes longer
5. **Parameter Not Found**: Ensure all required SSM parameters are created

## Cost Optimization

### Current Optimizations

- **Spot Instances**: 70% cost savings on training jobs
- **Fargate Spot**: 70% cost savings on ECS tasks
- **S3 Intelligent-Tiering**: Automatic cost optimization for feature snapshots
- **Model Compression**: gzip compression for model artifacts
- **Resource Termination**: Automatic cleanup after job completion

### Cost Monitoring

Track ML pipeline costs:

```bash
# View cost metrics
aws cloudwatch get-metric-statistics \
  --namespace BitoGuard/MLPipeline \
  --metric-name MonthlyCost \
  --start-time $(date -u -d '30 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Sum

# Use AWS Cost Explorer for detailed breakdown
echo "https://console.aws.amazon.com/cost-management/home#/cost-explorer"
```

## Maintenance

### Updating Docker Images

```bash
# Rebuild and push updated images
docker build -f bitoguard_core/Dockerfile.training -t bitoguard-training:latest bitoguard_core/
docker tag bitoguard-training:latest ${ECR_REPO}:training
docker push ${ECR_REPO}:training

# No restart needed - next pipeline execution uses new image
```

### Updating Lambda Functions

```bash
# Update function code
cd infra/aws/lambda/drift_detector
zip -r ../drift_detector.zip lambda_function.py

# Deploy via Terraform
cd ../../terraform
terraform apply -target=aws_lambda_function.drift_detector
```

### Updating Configuration

```bash
# Update SSM parameters
aws ssm put-parameter \
  --name "/bitoguard/ml-pipeline/training/lgbm/learning_rate" \
  --value "0.04" \
  --overwrite

# Changes take effect on next pipeline execution
```

## Security Best Practices

1. **IAM Roles**: Use least-privilege IAM roles for all services
2. **Secrets Management**: Store API keys in AWS Secrets Manager
3. **VPC Configuration**: Deploy SageMaker endpoints in private subnets
4. **Encryption**: Enable S3 bucket encryption and EFS encryption at rest
5. **Logging**: Enable CloudTrail for audit logging
6. **Access Control**: Use IAM policies to restrict access to sensitive resources

## Next Steps

- Set up CloudWatch alarms for critical metrics
- Configure SNS email subscriptions for alerts
- Implement model A/B testing with SageMaker endpoints
- Set up automated model retraining triggers based on drift
- Integrate with CI/CD pipeline for automated deployments

## Support

For issues or questions:
- Check CloudWatch Logs for error messages
- Review Terraform state for infrastructure issues
- Consult AWS SageMaker documentation for service-specific questions
- Contact DevOps team for deployment assistance
