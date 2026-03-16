# SageMaker Structured Logging Guide

## Overview

This document describes the structured logging approach for all SageMaker stages in the BitoGuard ML Pipeline.

## Log Format

All logs follow a consistent JSON structure:

```json
{
  "timestamp": "2026-03-15T12:00:00Z",
  "execution_id": "exec_abc123",
  "stage": "processing|training|tuning|registration|endpoint|batch_transform",
  "level": "INFO|WARNING|ERROR",
  "message": "Human-readable message",
  "metadata": {
    "job_name": "bitoguard-lgbm-20260315-120000",
    "model_type": "lgbm",
    "instance_type": "ml.m5.xlarge",
    "duration_seconds": 1850
  },
  "metrics": {
    "rows_processed": 150000,
    "features_generated": 155,
    "precision_at_100": 0.82
  }
}
```

## Processing Jobs

### Entry Point Logging

The `preprocessing_entrypoint.py` script logs:

```python
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Structured log helper
def log_structured(level, message, metadata=None, metrics=None):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "execution_id": os.environ.get("PROCESSING_JOB_NAME", "unknown"),
        "stage": "processing",
        "level": level,
        "message": message,
        "metadata": metadata or {},
        "metrics": metrics or {}
    }
    logger.log(getattr(logging, level), json.dumps(log_entry))

# Usage examples
log_structured("INFO", "Starting data preprocessing", 
               metadata={"data_source": "efs", "snapshot_id": "20260315T120000Z"})

log_structured("INFO", "Preprocessing completed", 
               metrics={"rows_processed": 150000, "features_generated": 155, 
                       "feature_completeness": 0.98})
```

### Key Log Points

1. **Job Start**: Log configuration and input paths
2. **Data Loading**: Log row counts and data sources
3. **Feature Engineering**: Log feature counts and computation time
4. **Quality Report**: Log completeness, null percentages, outliers
5. **Output Saving**: Log output paths and file sizes
6. **Job Complete**: Log total duration and summary metrics

## Training Jobs

### Entry Point Logging

The `train_entrypoint.py` script logs:

```python
log_structured("INFO", "Starting model training",
               metadata={"model_type": "lgbm", "hyperparameters": hyperparams})

log_structured("INFO", "Training completed",
               metrics={"precision_at_100": 0.82, "auc": 0.89, 
                       "training_time_seconds": 1200})
```

### Metric Logging for Tuning

For hyperparameter tuning, metrics must be logged in SageMaker-compatible format:

```python
# Print metrics in regex-parseable format
print(f"precision_at_100: {result['precision_at_100']}")
print(f"valid_logloss: {result['validation_logloss']}")
print(f"auc: {result['auc']}")
```

### Key Log Points

1. **Job Start**: Log model type and hyperparameters
2. **Data Loading**: Log training/validation split sizes
3. **Training Progress**: Log epoch metrics (if applicable)
4. **Model Evaluation**: Log validation metrics
5. **Artifact Saving**: Log model file paths and sizes
6. **Job Complete**: Log total training time

## Hyperparameter Tuning Jobs

### Tuning Analyzer Lambda Logging

The `tuning_analyzer` Lambda logs:

```python
logger.info(json.dumps({
    "timestamp": datetime.utcnow().isoformat(),
    "stage": "tuning",
    "level": "INFO",
    "message": "Analyzing tuning job results",
    "metadata": {
        "tuning_job_name": tuning_job_name,
        "total_training_jobs": len(training_jobs),
        "best_job_name": best_job_name
    },
    "metrics": {
        "best_precision_at_100": best_metric_value,
        "tuning_duration_seconds": tuning_duration
    }
}))
```

### Key Log Points

1. **Tuning Start**: Log strategy, objective metric, parameter ranges
2. **Training Job Complete**: Log each training job result
3. **Best Model Selection**: Log best hyperparameters and metrics
4. **Tuning Complete**: Log total jobs, duration, best result

## Model Registration

### Registration Lambda Logging

The `model_registry` Lambda logs:

```python
logger.info(json.dumps({
    "timestamp": datetime.utcnow().isoformat(),
    "stage": "registration",
    "level": "INFO",
    "message": "Registering model in SageMaker Model Registry",
    "metadata": {
        "training_job_name": training_job_name,
        "model_type": model_type,
        "model_package_group": model_package_group_name,
        "approval_status": "PendingManualApproval"
    },
    "metrics": {
        "precision_at_100": training_metrics.get("precision_at_100"),
        "model_size_mb": model_size_mb
    }
}))
```

### Key Log Points

1. **Registration Start**: Log training job and model type
2. **Metadata Extraction**: Log extracted hyperparameters and metrics
3. **Package Creation**: Log model package ARN
4. **Registration Complete**: Log approval status

## Endpoint Deployment

### Deployment Lambda Logging

```python
logger.info(json.dumps({
    "timestamp": datetime.utcnow().isoformat(),
    "stage": "endpoint",
    "level": "INFO",
    "message": "Deploying model to endpoint",
    "metadata": {
        "endpoint_name": endpoint_name,
        "model_name": model_name,
        "instance_type": "ml.t3.medium",
        "initial_instance_count": 1
    }
}))
```

### Key Log Points

1. **Deployment Start**: Log endpoint configuration
2. **Model Loading**: Log model package version
3. **Endpoint Creation**: Log endpoint ARN
4. **Health Check**: Log endpoint status
5. **Deployment Complete**: Log endpoint URL

## Batch Transform Jobs

### Transform Job Logging

```python
log_structured("INFO", "Starting batch transform",
               metadata={"transform_job_name": job_name, 
                        "input_s3_uri": input_uri,
                        "batch_size": 100})

log_structured("INFO", "Batch transform completed",
               metrics={"records_processed": 10000, 
                       "duration_seconds": 600,
                       "predictions_generated": 10000})
```

### Key Log Points

1. **Job Start**: Log input/output paths and batch size
2. **Processing Progress**: Log batch completion (if available)
3. **Results Processing**: Log prediction statistics
4. **Job Complete**: Log total records and duration

## CloudWatch Logs Integration

### Log Groups

All SageMaker logs are sent to dedicated log groups:

- `/aws/sagemaker/ProcessingJobs` - Processing job logs
- `/aws/sagemaker/TrainingJobs` - Training job logs
- `/aws/sagemaker/Endpoints` - Endpoint invocation logs
- `/aws/stepfunctions/${name_prefix}-ml-pipeline` - Step Functions execution logs

### Log Retention

- Processing/Training/Endpoint logs: 30 days
- Step Functions logs: 30 days
- Lambda function logs: 14 days

### Log Insights Queries

#### Find Failed Jobs

```
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc
| limit 20
```

#### Training Job Metrics

```
fields @timestamp, @message
| filter @message like /precision_at_100/
| parse @message "precision_at_100: *" as metric_value
| sort @timestamp desc
```

#### Processing Job Duration

```
fields @timestamp, @message
| filter @message like /Processing completed/
| parse @message '"duration_seconds": *' as duration
| stats avg(duration), max(duration), min(duration)
```

## Best Practices

1. **Always log structured JSON** for easy parsing and querying
2. **Include execution_id** to correlate logs across stages
3. **Log both metadata and metrics** for comprehensive observability
4. **Use appropriate log levels**: INFO for normal flow, WARNING for recoverable issues, ERROR for failures
5. **Log timing information** for performance analysis
6. **Include resource information** (instance types, counts) for cost tracking
7. **Log input/output paths** for data lineage tracking

## Error Handling

Always log errors with full context:

```python
try:
    result = train_model()
except Exception as e:
    log_structured("ERROR", f"Training failed: {str(e)}",
                   metadata={"model_type": model_type, 
                            "error_type": type(e).__name__,
                            "traceback": traceback.format_exc()})
    raise
```

## Monitoring and Alerting

CloudWatch alarms are configured to trigger on:

- Processing job failures
- Training job failures
- Tuning job failures
- Endpoint latency > 200ms at p95
- Batch transform failures

All critical errors send notifications to the `critical_errors` SNS topic.
