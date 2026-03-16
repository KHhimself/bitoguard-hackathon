# Ensemble Stacker with 5-Fold Cross-Validation

## Overview

The BitoGuard ML pipeline now includes an ensemble stacker model that uses **StratifiedGroupKFold with 5 folds** for out-of-fold (OOF) predictions. This provides robust model training and prevents data leakage by ensuring users in the same group stay together during cross-validation.

## Architecture

### Model Components

1. **Base Models** (trained in parallel):
   - LightGBM: Gradient boosting with temporal splits
   - CatBoost: Gradient boosting with categorical feature support
   - IsolationForest: Anomaly detection

2. **Stacker Model** (trained sequentially after base models):
   - **Branch A**: CatBoost classifier
   - **Branch B**: LightGBM classifier
   - **Meta-Learner**: Logistic Regression

### Cross-Validation Strategy

**StratifiedGroupKFold (5 folds)**:
- **Stratified**: Maintains class distribution across folds
- **Grouped**: Keeps all snapshots of the same user_id together
- **5 Folds**: Provides robust OOF predictions with 80/20 train/val split per fold

This prevents data leakage where different snapshots of the same user appear in both training and validation sets.

## Training Process

### Step 1: Train Base Models (Parallel)
```
ParallelTraining:
├─ TrainLightGBM    (ml.m5.xlarge, 30-60 min)
├─ TrainCatBoost    (ml.m5.xlarge, 30-60 min)
└─ TrainIsolationForest (ml.m5.large, 15-30 min)
```

### Step 2: Train Stacker (Sequential)
```
TrainStacker:
1. Load processed features from S3
2. For each of 5 folds:
   a. Split data by user_id groups (StratifiedGroupKFold)
   b. Train CatBoost on training fold
   c. Train LightGBM on training fold
   d. Generate OOF predictions on validation fold
3. Train Logistic Regression meta-learner on all OOF predictions
4. Retrain final CatBoost on full training data
5. Retrain final LightGBM on full training data
6. Save all models (cb, lgbm, meta-learner)
```

## Data Flow

```
BitoPro API
    ↓
DataSyncStage (ECS)
    ↓
FeatureEngineeringStage (ECS)
    ↓
PreprocessingStage (SageMaker Processing)
    ↓
features/processed/*.parquet
    ↓
ParallelTraining (SageMaker Training)
├─ LightGBM → models/lgbm_*.joblib
├─ CatBoost → models/catboost_*.joblib
└─ IsolationForest → models/iforest_*.joblib
    ↓
TrainStacker (SageMaker Training)
    ↓
models/stacker_*/ (3 files)
├─ cb_*.joblib (CatBoost branch)
├─ lgbm_v2_*.joblib (LightGBM branch)
└─ stacker_*.joblib (LR meta-learner)
```

## Implementation Details

### Training Entry Point

**File**: `bitoguard_core/ml_pipeline/train_entrypoint.py`

```python
def train_stacker_model(n_folds: int = 5) -> Dict[str, Any]:
    """
    Train ensemble stacker with k-fold cross-validation.
    
    Args:
        n_folds: Number of folds for cross-validation
        
    Returns:
        Training result dictionary
    """
    from models.stacker import train_stacker
    
    result = train_stacker(n_folds=n_folds)
    
    print(f"stacker_version: {result['stacker_version']}")
    print(f"n_folds: {n_folds}")
    
    return result
```

### Stacker Implementation

**File**: `bitoguard_core/models/stacker.py`

Key features:
- Uses `StratifiedGroupKFold` from scikit-learn
- Groups by `user_id` to prevent leakage
- Generates OOF predictions for meta-learner training
- Retrains final models on full training data
- Saves 3 model files: CatBoost, LightGBM, meta-learner

### Step Functions Integration

**File**: `infra/aws/terraform/step_functions.tf`

```hcl
TrainStacker = {
  Type     = "Task"
  Resource = "arn:aws:states:::sagemaker:createTrainingJob.sync"
  Parameters = {
    TrainingJobName = "bitoguard-stacker-$.Execution.Name"
    HyperParameters = {
      model_type = "stacker"
      n_folds    = "5"
    }
    ResourceConfig = {
      InstanceType   = "ml.m5.xlarge"
      InstanceCount  = 1
      VolumeSizeInGB = 30
    }
    EnableManagedSpotTraining = true
  }
}
```

## Model Registry

**Model Package Group**: `bitoguard-ml-stacker-models`

The stacker model is registered in SageMaker Model Registry with:
- Model version (timestamp-based)
- Training metadata (n_folds, feature columns)
- Branch model paths (CatBoost, LightGBM)
- Meta-learner coefficients
- Approval status (PendingManualApproval)

## Configuration

### SageMaker Training Job

- **Instance Type**: ml.m5.xlarge
- **Volume Size**: 30 GB
- **Timeout**: 3600 seconds (1 hour)
- **Spot Instances**: Enabled (70% cost reduction)
- **Input**: Processed features from S3
- **Output**: 3 model files to S3

### Hyperparameters

- `model_type`: "stacker" (required)
- `n_folds`: 5 (default, configurable)

### Cost Estimate

- **Instance Cost**: ~$0.23/hour (ml.m5.xlarge on-demand)
- **Spot Cost**: ~$0.07/hour (70% discount)
- **Training Duration**: 30-60 minutes
- **Monthly Cost**: ~$3-5/month (daily training with spot instances)

## Usage

### Automatic Training

The stacker trains automatically after base models in the pipeline:

```bash
# Start full pipeline (includes stacker)
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"skip_training":false}'
```

### Custom Fold Count

```bash
# Train with custom number of folds
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{"skip_training":false,"stacker_n_folds":10}'
```

### Model Approval

```python
from ml_pipeline.model_approval import approve_model, get_approved_model

# List pending stacker models
pending = list_pending_approvals("bitoguard-ml-stacker-models")

# Approve a stacker model
approve_model(
    model_package_arn=pending[0]['model_package_arn'],
    approval_description="Validated with 5-fold CV, P@100=0.96"
)

# Get latest approved stacker
stacker = get_approved_model("bitoguard-ml-stacker-models")
print(f"Stacker: {stacker['model_package_arn']}")
```

## Monitoring

### CloudWatch Logs

```bash
# View stacker training logs
aws logs tail /aws/sagemaker/TrainingJobs/bitoguard-stacker-* --follow
```

### Training Metrics

The stacker training logs include:
- Fold-by-fold training progress
- OOF prediction statistics
- Meta-learner training metrics
- Final model paths

### Model Artifacts

```bash
# List stacker models in S3
aws s3 ls s3://bitoguard-ml-artifacts/models/ --recursive | grep stacker

# Download stacker model
aws s3 cp s3://bitoguard-ml-artifacts/models/stacker_20260315T120000Z/ . --recursive
```

## Benefits of 5-Fold CV

1. **Robust Evaluation**: OOF predictions provide unbiased performance estimates
2. **Reduced Overfitting**: Meta-learner trained on out-of-fold predictions
3. **Data Efficiency**: Uses all training data for both training and validation
4. **Leakage Prevention**: StratifiedGroupKFold keeps user snapshots together
5. **Ensemble Diversity**: Multiple base models capture different patterns

## Comparison with Base Models

| Model | Training Method | Validation | Ensemble |
|-------|----------------|------------|----------|
| LightGBM | Temporal split | Single holdout | No |
| CatBoost | Temporal split | Single holdout | No |
| IsolationForest | Unsupervised | N/A | No |
| **Stacker** | **5-fold CV** | **OOF predictions** | **Yes (CB + LGBM + LR)** |

## Performance Expectations

Based on the existing stacker implementation:
- **Precision@100**: Typically 5-10% improvement over single models
- **Recall**: Better coverage through ensemble diversity
- **Calibration**: Improved probability estimates from meta-learner
- **Robustness**: More stable predictions across different data distributions

## Troubleshooting

### Stacker Training Fails

```bash
# Check logs
aws logs tail /aws/sagemaker/TrainingJobs/bitoguard-stacker-* --follow

# Common issues:
# 1. Insufficient memory → Increase instance type to ml.m5.2xlarge
# 2. Timeout → Increase MaxRuntimeInSeconds
# 3. Missing features → Check preprocessing stage output
```

### OOF Predictions Quality

The stacker implementation includes validation of OOF predictions:
- Checks for NaN values
- Validates prediction ranges [0, 1]
- Ensures all folds have predictions

### Model Loading Issues

```python
# Verify stacker model files exist
from pathlib import Path
model_dir = Path("artifacts/models")
stacker_files = list(model_dir.glob("stacker_*"))
print(f"Found {len(stacker_files)} stacker model sets")
```

## Future Enhancements

1. **Hyperparameter Tuning**: Add tuning for stacker hyperparameters (C, iterations, depth)
2. **Additional Base Models**: Include XGBoost, Neural Networks
3. **Feature Selection**: Per-fold feature importance analysis
4. **Calibration**: Post-hoc calibration of ensemble predictions
5. **Online Learning**: Incremental updates to meta-learner

## References

- Stacker Implementation: `bitoguard_core/models/stacker.py`
- Training Entry Point: `bitoguard_core/ml_pipeline/train_entrypoint.py`
- Step Functions Config: `infra/aws/terraform/step_functions.tf`
- Model Registry: `infra/aws/terraform/sagemaker_model_registry.tf`
