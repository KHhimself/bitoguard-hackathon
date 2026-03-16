# SageMaker Features Quick Reference

## Common Commands

### Deployment

```bash
# Deploy all SageMaker features
./scripts/deploy-sagemaker-features.sh

# Deploy only Terraform changes
cd infra/aws/terraform
terraform apply
```

### Pipeline Execution

```bash
# Get state 
machine ARN
STATE_MACHINE_ARN=$(aws stepfunctions list-state-machines --query "stateMachines[?contains(name, 'bitoguard-ml-pipeline')].stateMachineArn" --output text)

# Start preprocessing only (quick test)
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"skip_training":true}'

# Start full pipeline
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"skip_training":false,"enable_tuning":false}'

# Start with hyperparameter tuning
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"skip_training":false,"enable_tuning":true}'

# Monitor execution
EXECUTION_ARN="<your-execution-arn>"
aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN
```

### Model Registry

```bash
# List model package groups
aws sagemaker list-model-package-groups --query "ModelPackageGroupSummaryList[?contains(ModelPackageGroupName, 'bitoguard')]"

# List pending approvals
aws sagemaker list-model-packages \
  --model-package-group-name bitoguard-ml-lgbm-models \
  --model-approval-status PendingManualApproval

# Approve a model
aws sagemaker update-model-package \
  --model-package-arn <model-package-arn> \
  --model-approval-status Approved \
  --approval-description "Validated with P@100=0.95"

# Get latest approved model
aws sagemaker list-model-packages \
  --model-package-group-name bitoguard-ml-lgbm-models \
  --model-approval-status Approved \
  --sort-by CreationTime \
  --sort-order Descending \
  --max-results 1
```

### Python API

```python
# Approve a model
from ml_pipeline.model_approval import approve_model

approve_model(
    model_package_arn="arn:aws:sagemaker:...",
    approval_description="Validated on test set"
)

# Get latest approved model
from ml_pipeline.model_approval import get_approved_model

model = get_approved_model("bitoguard-ml-lgbm-models")
print(f"Model: {model['model_package_arn']}")
print(f"Metrics: {model['customer_metadata']}")

# List pending approvals
from ml_pipeline.model_approval import list_pending_approvals

pending = list_pending_approvals("bitoguard-ml-lgbm-models")
for model in pending:
    print(f"{model['model_package_arn']} - {model['creation_time']}")
```

### Monitoring

```bash
# View processing job logs
aws logs tail /aws/sagemaker/ProcessingJobs/bitoguard-preprocessing-* --follow

# View training job logs
aws logs tail /aws/sagemaker/TrainingJobs/bitoguard-lgbm-* --follow

# View tuning analyzer logs
aws logs tail /aws/lambda/bitoguard-ml-tuning-analyzer --follow

# View model registry logs
aws logs tail /aws/lambda/bitoguard-ml-model-registry --follow

# List recent processing jobs
aws sagemaker list-processing-jobs \
  --name-contains bitoguard \
  --sort-by CreationTime \
  --sort-order Descending \
  --max-results 10

# List recent training jobs
aws sagemaker list-training-jobs \
  --name-contains bitoguard \
  --sort-by CreationTime \
  --sort-order Descending \
  --max-results 10

# List tuning jobs
aws sagemaker list-hyper-parameter-tuning-jobs \
  --name-contains bitoguard \
  --sort-by CreationTime \
  --sort-order Descending
```

### Data Quality Reports

```bash
# Download latest quality report
aws s3 cp s3://bitoguard-ml-artifacts/quality-reports/data_quality_report.json - | jq .

# List all quality reports
aws s3 ls s3://bitoguard-ml-artifacts/quality-reports/ --recursive

# View specific report
aws s3 cp s3://bitoguard-ml-artifacts/quality-reports/20260315T120000Z/data_quality_report.json - | jq .
```

### Tuning Results

```bash
# List tuning jobs
aws sagemaker list-hyper-parameter-tuning-jobs --query "HyperParameterTuningJobSummaries[?contains(HyperParameterTuningJobName, 'bitoguard')]"

# Get tuning job details
aws sagemaker describe-hyper-parameter-tuning-job \
  --hyper-parameter-tuning-job-name bitoguard-lgbm-tuning-*

# Download tuning analysis
aws s3 cp s3://bitoguard-ml-artifacts/tuning-analysis/bitoguard-lgbm-tuning-*/analysis.json - | jq .

# Get best training job
aws sagemaker describe-hyper-parameter-tuning-job \
  --hyper-parameter-tuning-job-name bitoguard-lgbm-tuning-* \
  --query "BestTrainingJob.{Name:TrainingJobName,Metric:FinalHyperParameterTuningJobObjectiveMetric.Value,Params:TunedHyperParameters}"
```

### Configuration

```bash
# Enable/disable tuning
aws ssm put-parameter \
  --name /bitoguard/ml-pipeline/tuning/enabled \
  --value "true" \
  --overwrite

# Update tuning max jobs
aws ssm put-parameter \
  --name /bitoguard/ml-pipeline/tuning/max_jobs \
  --value "20" \
  --overwrite

# Update tuning parallel jobs
aws ssm put-parameter \
  --name /bitoguard/ml-pipeline/tuning/max_parallel_jobs \
  --value "3" \
  --overwrite

# View all tuning parameters
aws ssm get-parameters-by-path \
  --path /bitoguard/ml-pipeline/tuning \
  --recursive
```

### Cost Monitoring

```bash
# View SageMaker costs (last 30 days)
aws ce get-cost-and-usage \
  --time-period Start=$(date -d '30 days ago' +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --filter file://<(echo '{
    "Dimensions": {
      "Key": "SERVICE",
      "Values": ["Amazon SageMaker"]
    }
  }')

# View costs by usage type
aws ce get-cost-and-usage \
  --time-period Start=$(date -d '30 days ago' +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=USAGE_TYPE \
  --filter file://<(echo '{
    "Dimensions": {
      "Key": "SERVICE",
      "Values": ["Amazon SageMaker"]
    }
  }')
```

### Troubleshooting

```bash
# Check processing job status
aws sagemaker describe-processing-job \
  --processing-job-name bitoguard-preprocessing-*

# Check training job status
aws sagemaker describe-training-job \
  --training-job-name bitoguard-lgbm-*

# Check for failed jobs
aws sagemaker list-processing-jobs \
  --status-equals Failed \
  --name-contains bitoguard

aws sagemaker list-training-jobs \
  --status-equals Failed \
  --name-contains bitoguard

# View job failure reason
aws sagemaker describe-processing-job \
  --processing-job-name <job-name> \
  --query "FailureReason"

# Check Lambda function errors
aws lambda get-function \
  --function-name bitoguard-ml-tuning-analyzer

aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=bitoguard-ml-tuning-analyzer \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```

## File Locations

### Code
- Processing entry point: `bitoguard_core/ml_pipeline/preprocessing_entrypoint.py`
- Training entry point: `bitoguard_core/ml_pipeline/train_entrypoint.py`
- Model approval: `bitoguard_core/ml_pipeline/model_approval.py`

### Infrastructure
- Tuning config: `infra/aws/terraform/sagemaker_tuning.tf`
- Model registry: `infra/aws/terraform/sagemaker_model_registry.tf`
- Step Functions: `infra/aws/terraform/step_functions.tf`
- Lambda functions: `infra/aws/lambda/`

### Documentation
- Implementation guide: `docs/SAGEMAKER_FEATURES_IMPLEMENTATION.md`
- Implementation summary: `docs/SAGEMAKER_IMPLEMENTATION_SUMMARY.md`
- Deployment checklist: `docs/SAGEMAKER_DEPLOYMENT_CHECKLIST.md`

### Artifacts (S3)
- Processed features: `s3://bitoguard-ml-artifacts/features/processed/`
- Quality reports: `s3://bitoguard-ml-artifacts/quality-reports/`
- Models: `s3://bitoguard-ml-artifacts/models/`
- Tuning results: `s3://bitoguard-ml-artifacts/tuning-results/`
- Tuning analysis: `s3://bitoguard-ml-artifacts/tuning-analysis/`

## Key Metrics

### Processing Jobs
- **Duration**: ~10-20 minutes (ml.m5.xlarge)
- **Cost**: ~$0.50 per job (spot instances)
- **Output**: Parquet features + quality report

### Training Jobs (without tuning)
- **Duration**: ~30-60 minutes per model (ml.m5.xlarge)
- **Cost**: ~$1.50 per job (spot instances)
- **Output**: Trained model + metadata

### Hyperparameter Tuning
- **Duration**: 2-4 hours (20 jobs × 3 parallel)
- **Cost**: ~$30 per tuning run (spot instances)
- **Output**: Best hyperparameters + all job results

### Model Registry
- **Storage**: Metadata only (minimal cost)
- **Versioning**: Automatic
- **Approval**: Manual workflow

## Environment Variables

### Processing Job
- `DATA_SOURCE`: "efs" or "s3"
- `S3_INPUT_URI`: S3 URI for input data (if DATA_SOURCE=s3)
- `FEATURE_STORE_BUCKET`: S3 bucket for feature store
- `SNAPSHOT_ID`: Snapshot identifier

### Training Job
- `TRAINING_JOB_NAME`: SageMaker training job name (auto-set)
- `LGBM_*`: LightGBM hyperparameters (optional overrides)
- `CATBOOST_*`: CatBoost hyperparameters (optional overrides)

## SSM Parameters

### Tuning Configuration
- `/bitoguard/ml-pipeline/tuning/enabled`: "true" or "false"
- `/bitoguard/ml-pipeline/tuning/max_jobs`: Max training jobs (default: 20)
- `/bitoguard/ml-pipeline/tuning/max_parallel_jobs`: Parallel jobs (default: 3)
- `/bitoguard/ml-pipeline/tuning/objective_metric`: Metric to optimize (default: precision_at_100)

### Training Configuration
- `/bitoguard/ml-pipeline/training/lgbm/*`: LightGBM hyperparameters
- `/bitoguard/ml-pipeline/training/catboost/*`: CatBoost hyperparameters
- `/bitoguard/ml-pipeline/training/iforest/*`: IsolationForest hyperparameters

## IAM Roles

- `bitoguard-ml-sagemaker-execution`: SageMaker jobs execution role
- `bitoguard-ml-tuning-analyzer-role`: Tuning analyzer Lambda role
- `bitoguard-ml-model-registry-role`: Model registry Lambda role
- `bitoguard-ml-stepfunctions-execution`: Step Functions execution role

## Model Package Groups

- `bitoguard-ml-lgbm-models`: LightGBM models
- `bitoguard-ml-catboost-models`: CatBoost models
- `bitoguard-ml-iforest-models`: IsolationForest models

## Lambda Functions

- `bitoguard-ml-tuning-analyzer`: Analyzes tuning results
- `bitoguard-ml-model-registry`: Registers trained models

## CloudWatch Log Groups

- `/aws/sagemaker/ProcessingJobs/bitoguard-preprocessing-*`
- `/aws/sagemaker/TrainingJobs/bitoguard-*`
- `/aws/lambda/bitoguard-ml-tuning-analyzer`
- `/aws/lambda/bitoguard-ml-model-registry`
- `/aws/states/bitoguard-ml-pipeline`
