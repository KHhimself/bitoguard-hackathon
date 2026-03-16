# SageMaker Features Implementation Guide

## Overview

This document describes the SageMaker features implemented for the BitoGuard ML Pipeline, including Processing Jobs, Hyperparameter Tuning, and Model Registry.

## Implemented Features

### 1. SageMaker Processing Jobs

**Purpose**: Scalable data preprocessing and feature engineering with quality reporting.

**Components**:
- `bitoguard_core/Dockerfile.processing` - Processing container
- `bitoguard_core/ml_pipeline/preprocessing_entrypoint.py` - Entry point script
- Step Functions `PreprocessingStage` - Orchestration

**Usage**:
```python
# The preprocessing stage runs automatically in the pipeline
# It generates:
# - Processed features in Parquet format
# - Data quality reports with null percentages, outliers, distributions
# - Feature store snapshots (optional)
```

**Configuration**:
- Instance Type: `ml.m5.xlarge`
- Volume Size: 30 GB
- Timeout: 3600 seconds
- Spot Instances: Enabled

### 2. SageMaker Hyperparameter Tuning

**Purpose**: Automated hyperparameter optimization using Bayesian search.

**Components**:
- Enhanced `train_entrypoint.py` with tunable parameters
- `infra/aws/terraform/sagemaker_tuning.tf` - Configuration
- `infra/aws/lambda/tuning_analyzer/` - Results analysis
- Step Functions `HyperparameterTuning` stage

**Tunable Parameters**:

**LightGBM** (9 parameters):
- `learning_rate`: 0.01 - 0.3 (Logarithmic)
- `num_leaves`: 20 - 100
- `n_estimators`: 100 - 500
- `subsample`: 0.6 - 1.0
- `colsample_bytree`: 0.6 - 1.0
- `min_data_in_leaf`: 10 - 100
- `max_depth`: 3 - 12
- `reg_alpha`: 0.0 - 1.0
- `reg_lambda`: 0.0 - 1.0

**CatBoost** (6 parameters):
- `learning_rate`: 0.01 - 0.3 (Logarithmic)
- `depth`: 4 - 10
- `n_estimators`: 100 - 500
- `subsample`: 0.6 - 1.0
- `colsample_bytree`: 0.6 - 1.0
- `l2_leaf_reg`: 1.0 - 10.0

**Optimization Settings**:
- Strategy: Bayesian
- Objective Metric: `precision_at_100` (Maximize)
- Max Training Jobs: 20
- Max Parallel Jobs: 3
- Spot Instances: Enabled

**Enabling Tuning**:
```bash
# Set SSM parameter
aws ssm put-parameter \
  --name /bitoguard/ml-pipeline/tuning/enabled \
  --value "true" \
  --overwrite

# Or pass in execution input
{
  "enable_tuning": true
}
```

**Analyzing Results**:
```python
# The tuning analyzer Lambda extracts:
# - Best hyperparameters
# - All training job results
# - Performance metrics
# - Saves to S3: s3://bucket/tuning-analysis/
```

### 3. SageMaker Model Registry

**Purpose**: Centralized model versioning with approval workflows.

**Components**:
- `infra/aws/terraform/sagemaker_model_registry.tf` - Model package groups
- `infra/aws/lambda/model_registry/` - Registration Lambda
- `bitoguard_core/ml_pipeline/model_approval.py` - Approval workflow

**Model Package Groups**:
- `bitoguard-ml-lgbm-models` - LightGBM models
- `bitoguard-ml-catboost-models` - CatBoost models
- `bitoguard-ml-iforest-models` - IsolationForest models
- `bitoguard-ml-stacker-models` - Ensemble stacker models (NEW)

**Registering Models**:
```python
# Automatic registration after training (via Lambda)
# Or manual registration:
from ml_pipeline.model_approval import ModelApprovalWorkflow

workflow = ModelApprovalWorkflow()
# Models are registered with PendingManualApproval status
```

**Approval Workflow**:
```python
from ml_pipeline.model_approval import approve_model, get_approved_model

# Approve a model
approve_model(
    model_package_arn="arn:aws:sagemaker:...",
    approval_description="Validated on test set with P@100=0.95"
)

# Get latest approved model
model = get_approved_model("bitoguard-ml-lgbm-models")
print(f"Model ARN: {model['model_package_arn']}")
print(f"Model Data: {model['model_data_url']}")
```

**Listing Pending Approvals**:
```python
from ml_pipeline.model_approval import list_pending_approvals

pending = list_pending_approvals("bitoguard-ml-lgbm-models")
for model in pending:
    print(f"{model['model_package_arn']} - {model['creation_time']}")
```

### 4. Ensemble Stacker with 5-Fold Cross-Validation (NEW)

**Purpose**: Train ensemble stacker model using StratifiedGroupKFold with 5 folds for out-of-fold predictions.

**Components**:
- Enhanced `train_entrypoint.py` with stacker support
- `models/stacker.py` - Stacker implementation with k-fold CV
- Step Functions `TrainStacker` stage - Sequential training after base models

**Architecture**:
- **Base Models**: CatBoost + LightGBM (trained in parallel)
- **Meta-Learner**: Logistic Regression
- **Cross-Validation**: StratifiedGroupKFold (5 folds, grouped by user_id)
- **OOF Predictions**: Out-of-fold predictions used to train meta-learner

**Training Process**:
1. Train LightGBM, CatBoost, IsolationForest in parallel
2. Train stacker sequentially using base model outputs
3. For each fold:
   - Train CatBoost on training fold
   - Train LightGBM on training fold
   - Generate OOF predictions on validation fold
4. Train Logistic Regression meta-learner on all OOF predictions
5. Retrain final base models on full training data

**Configuration**:
- Instance Type: `ml.m5.xlarge`
- Volume Size: 30 GB
- Timeout: 3600 seconds
- Spot Instances: Enabled
- Default Folds: 5 (configurable via `n_folds` parameter)

**Usage**:
```bash
# Stacker trains automatically after base models
# To customize number of folds:
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"skip_training":false,"stacker_n_folds":5}'
```
```

## Integration with Step Functions

### Pipeline Flow

```
ValidateConfiguration
  ↓
DataSyncStage
  ↓
FeatureEngineeringStage
  ↓
PreprocessingStage (NEW)
  ↓
CheckSkipTraining
  ↓
CheckTuningEnabled (NEW)
  ↓ (if tuning enabled)
HyperparameterTuning (NEW)
  ├─ TuneLightGBM
  └─ TuneCatBoost
  ↓ (if tuning disabled)
ParallelTraining
  ├─ TrainLightGBM
  ├─ TrainCatBoost
  └─ TrainIsolationForest
  ↓
ScoringStage
  ↓
DriftDetection
  ↓
PublishMetrics
  ↓
NotifySuccess
```

### Execution Input

```json
{
  "execution_id": "manual-2026-03-15",
  "skip_training": false,
  "enable_tuning": false,
  "baseline_snapshot_id": "20260301T120000Z",
  "current_snapshot_id": "20260315T120000Z"
}
```

## Cost Optimization

All SageMaker jobs use spot instances with automatic fallback:
- **Processing Jobs**: 70% cost reduction
- **Training Jobs**: 70% cost reduction
- **Tuning Jobs**: 70% cost reduction per training job

**Estimated Monthly Costs** (assuming daily full pipeline):
- Processing: ~$15/month (1 hour/day on ml.m5.xlarge spot)
- Training (no tuning): ~$30/month (3 jobs × 1 hour/day on ml.m5.xlarge spot)
- Training (with tuning): ~$200/month (20 jobs × 2 models × 1 hour on ml.m5.xlarge spot)
- Model Registry: Free (metadata storage only)

## Monitoring

### CloudWatch Metrics

**Processing Jobs**:
- `ProcessingJobStatus`
- `ProcessingJobDuration`
- `DataQualityScore`

**Tuning Jobs**:
- `TuningJobStatus`
- `BestMetricValue`
- `TotalTrainingJobs`

**Model Registry**:
- `ModelsRegistered`
- `ModelsApproved`
- `ModelsPendingApproval`

### CloudWatch Logs

- `/aws/sagemaker/ProcessingJobs/bitoguard-preprocessing-*`
- `/aws/sagemaker/TrainingJobs/bitoguard-*`
- `/aws/lambda/bitoguard-ml-tuning-analyzer`
- `/aws/lambda/bitoguard-ml-model-registry`

## Troubleshooting

### Processing Job Fails

```bash
# Check logs
aws logs tail /aws/sagemaker/ProcessingJobs/bitoguard-preprocessing-* --follow

# Check data quality report
aws s3 cp s3://bitoguard-ml-artifacts/quality-reports/latest.json -
```

### Tuning Job Not Finding Good Parameters

```bash
# Analyze tuning results
aws lambda invoke \
  --function-name bitoguard-ml-tuning-analyzer \
  --payload '{"tuning_job_name":"bitoguard-lgbm-tuning-*","bucket_name":"bitoguard-ml-artifacts"}' \
  response.json

# Review results
cat response.json | jq '.body'
```

### Model Registration Fails

```bash
# Check Lambda logs
aws logs tail /aws/lambda/bitoguard-ml-model-registry --follow

# Verify model artifacts exist
aws s3 ls s3://bitoguard-ml-artifacts/models/
```

## Best Practices

1. **Enable Tuning Periodically**: Run tuning monthly or when data distribution changes significantly
2. **Monitor Data Quality**: Review quality reports after each preprocessing job
3. **Approve Models Promptly**: Don't let models pile up in pending approval
4. **Use Spot Instances**: Always enabled for cost savings
5. **Archive Old Models**: Lifecycle policies automatically archive models after 90 days
6. **Track Lineage**: Model registry maintains full lineage from training job to deployment

## Next Steps

For production deployment:
1. Review and adjust hyperparameter ranges based on initial tuning results
2. Set up automated model approval based on validation metrics
3. Configure CloudWatch alarms for job failures
4. Implement A/B testing for model deployment (see Real-Time Endpoints)
5. Set up batch scoring for large-scale inference (see Batch Transform)

## References

- [SageMaker Processing Jobs Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/processing-job.html)
- [SageMaker Hyperparameter Tuning Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/automatic-model-tuning.html)
- [SageMaker Model Registry Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html)
