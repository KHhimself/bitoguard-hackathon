# ML Pipeline Deployment Guide

This guide covers deploying the automated ML operations pipeline for BitoGuard using AWS-native services.

## Architecture Overview

The ML pipeline uses:
- **Step Functions**: Orchestrates the entire workflow
- **SageMaker**: Trains ML models (LightGBM, CatBoost, IsolationForest)
- **ECS Fargate**: Runs data sync, feature engineering, and scoring tasks
- **Lambda**: Drift detection, config validation, manual triggering
- **EventBridge**: Scheduled pipeline execution
- **S3**: Model registry and feature store
- **EFS**: Shared DuckDB storage
- **CloudWatch**: Monitoring, logging, and alerting

## Prerequisites

1. **AWS Account** with appropriate permissions
2. **AWS CLI** configured with credentials
3. **Terraform** >= 1.0
4. **Docker** for building container images
5. **Python 3.11** for Lambda packaging

## Deployment Steps

### 1. Configure Terraform Variables

Create `infra/aws/terraform/terraform.tfvars`:

```hcl
aws_region           = "us-east-1"
environment          = "prod"
project_name         = "bitoguard"
ml_notification_email = "your-email@example.com"
bitopro_api_url      = "https://aws-event-api.bitopro.com"
```

### 2. Run Deployment Script

```bash
cd scripts
./deploy-ml-pipeline.sh
```

The script will:
1. Build and push the training Docker image to ECR
2. Package Lambda functions
3. Initialize Terraform
4. Plan infrastructure changes
5. Apply Terraform configuration

### 3. Configure SSM Parameters

After deployment, configure pipeline parameters in AWS Systems Manager:

```bash
# Scheduling
aws ssm put-parameter --name /bitoguard/ml-pipeline/scheduling/daily_full_pipeline_cron \
  --value "cron(0 2 * * ? *)" --type String

# Training hyperparameters
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/n_estimators \
  --value "500" --type String

aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/learning_rate \
  --value "0.05" --type String

# Thresholds
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/feature_drift_kl \
  --value "0.1" --type String

aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/prediction_drift_percentage \
  --value "0.15" --type String

# Resources
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/sagemaker_instance_type \
  --value "ml.m5.xlarge" --type String
```

See `infra/aws/terraform/ssm_parameters.tf` for the complete list of parameters.

### 4. Test Manual Trigger

Trigger a test pipeline execution:

```bash
# Get the manual trigger URL from Terraform outputs
TRIGGER_URL=$(terraform output -raw manual_trigger_function_url)

# Trigger full pipeline
curl -X POST "$TRIGGER_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "execution_type": "full",
    "skip_training": false,
    "model_types": ["lgbm", "catboost", "iforest"]
  }'
```

### 5. Monitor Execution

1. **Step Functions Console**: View execution progress
   ```
   https://console.aws.amazon.com/states/home?region=us-east-1#/statemachines
   ```

2. **CloudWatch Dashboard**: View metrics and logs
   ```
   https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=bitoguard-prod-ml-pipeline
   ```

3. **CloudWatch Logs**: View detailed logs
   ```
   aws logs tail /ecs/bitoguard-prod-ml-pipeline --follow
   ```

## Pipeline Execution Flow

1. **ValidateConfiguration**: Validates SSM parameters
2. **DataSyncStage**: Syncs data from BitoPro API to DuckDB
3. **FeatureEngineeringStage**: Builds features and exports to S3
4. **ParallelTraining**: Trains 3 models in parallel on SageMaker
   - LightGBM
   - CatBoost
   - IsolationForest
5. **ScoringStage**: Scores users and generates alerts
6. **DriftDetection**: Detects feature and prediction drift
7. **PublishMetrics**: Publishes execution metrics
8. **NotifySuccess**: Sends success notification

## Scheduled Execution

The pipeline runs automatically:
- **Daily Full Pipeline**: 2 AM UTC (includes training)
- **Incremental Refresh**: Every 4 hours at 8 AM, 12 PM, 4 PM, 8 PM UTC (scoring only)

## Cost Optimization

The pipeline includes several cost optimizations:

1. **Fargate Spot**: 70% of ECS tasks use Spot instances
2. **SageMaker Spot**: All training jobs use Spot instances
3. **S3 Intelligent-Tiering**: Automatic cost optimization for features
4. **S3 Lifecycle Policies**: Archive old models to Glacier after 90 days
5. **Resource Termination**: Tasks terminate immediately after completion

Expected monthly cost: $200-400 depending on data volume and execution frequency.

## Monitoring and Alerts

### CloudWatch Alarms

The following alarms are configured:
- Pipeline execution failure
- Pipeline duration exceeds 2 hours
- Feature drift count exceeds 5
- Prediction drift exceeds 15%

### SNS Topics

Notifications are sent to:
- `bitoguard-prod-ml-pipeline-notifications`: General pipeline events
- `bitoguard-prod-drift-alerts`: Drift detection alerts
- `bitoguard-prod-critical-errors`: Critical failures

Subscribe to these topics in the SNS console.

## Troubleshooting

### Pipeline Execution Fails

1. Check CloudWatch Logs for error messages
2. Verify SSM parameters are configured correctly
3. Check IAM role permissions
4. Verify EFS mount is accessible

### Training Job Fails

1. Check SageMaker training job logs
2. Verify training data exists in S3
3. Check instance type availability
4. Review hyperparameters in SSM

### Drift Detection Fails

1. Check Lambda function logs
2. Verify feature snapshots exist in S3
3. Check Lambda memory/timeout settings

## Rollback

To rollback a deployment:

```bash
cd infra/aws/terraform
terraform plan -destroy
terraform destroy
```

## Integration with Existing API

The ML pipeline integrates with the existing BitoGuard API:

1. **Shared EFS**: Both pipeline and API access the same DuckDB
2. **Model Registry**: API loads latest models from S3
3. **SNS Notifications**: API receives score availability notifications

No changes to the existing API deployment are required.

## Next Steps

1. Configure email subscriptions for SNS topics
2. Set up CloudWatch dashboard alerts
3. Review and adjust SSM parameters based on performance
4. Monitor first few pipeline executions
5. Optimize resource allocation based on actual usage

## Support

For issues or questions:
- Check CloudWatch Logs for detailed error messages
- Review Terraform state for resource configuration
- Consult AWS documentation for service-specific issues
