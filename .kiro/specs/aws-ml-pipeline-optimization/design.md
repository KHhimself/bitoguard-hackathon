# Design Document: AWS ML Pipeline Optimization

## Overview

This design specifies the architecture for automating BitoGuard's ML operations pipeline using AWS-native services. The system replaces manual `make` commands with a fully automated, scheduled, and monitored ML workflow orchestrated by AWS Step Functions.

### Current State

BitoGuard currently runs ML operations manually:
- Data sync: `make sync` (full) or `make refresh` (incremental)
- Feature engineering: `make features` or `make features-v2`
- Model training: `make train` (LightGBM, CatBoost, IsolationForest)
- Scoring: `make score`
- Drift detection: `make drift`

These operations execute on local machines or ECS tasks with manual triggering, no scheduling, and limited observability.

### Target State

The optimized system provides:
- **Automated Orchestration**: Step Functions state machine executing sync → features → train → score → alerts
- **Scheduled Execution**: EventBridge triggers for daily full runs and 4-hour incremental refreshes
- **Managed Training**: SageMaker training jobs with spot instances for cost optimization
- **Artifact Management**: S3-based model registry and feature store with versioning
- **Comprehensive Monitoring**: CloudWatch dashboards, alarms, and drift detection
- **Seamless Integration**: Backward-compatible with existing ECS API services and EFS-backed DuckDB

### Design Principles

1. **AWS-Native Services**: Leverage managed services (Step Functions, SageMaker, EventBridge) over custom orchestration
2. **Cost Optimization**: Use spot instances, Fargate Spot, and intelligent tiering to minimize costs
3. **Backward Compatibility**: Maintain existing DuckDB schema, model formats, and API contracts
4. **Observability First**: Structured logging, metrics, and alarms for all pipeline stages
5. **Fail-Fast**: Early validation, clear error messages, and automatic notifications on failure



## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         EventBridge Scheduler                        │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ Daily Full Run   │  │ 4-Hour Refresh   │  │ Manual Trigger   │  │
│  │ (cron: 0 2 * * *)│  │ (rate: 4 hours)  │  │ (API/Console)    │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
└───────────┼────────────────────┼────────────────────┼──────────────┘
            │                    │                    │
            └────────────────────┴────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Step Functions State   │
                    │  Machine (Orchestrator) │
                    └────────────┬────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
┌───────▼────────┐   ┌──────────▼──────────┐   ┌────────▼────────┐
│  Data Sync     │   │  Feature Engineering │   │  Model Training │
│  (ECS Fargate) │──▶│  (ECS Fargate)       │──▶│  (SageMaker)    │
│  - sync.py     │   │  - build_features.py │   │  - train.py     │
│  - refresh.py  │   │  - graph features    │   │  - train_cat.py │
└────────┬───────┘   └──────────┬──────────┘   └────────┬────────┘
         │                      │                        │
         │                      │                        │
         ▼                      ▼                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Shared Storage Layer                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ EFS (DuckDB) │  │ S3 (Features)│  │ S3 (Model Registry)  │  │
│  │ - bitoguard  │  │ - Parquet    │  │ - lgbm_*.lgbm        │  │
│  │   .duckdb    │  │ - Snappy     │  │ - iforest_*.joblib   │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────────────┘  │
└─────────┼──────────────────┼──────────────────┼──────────────────┘
          │                  │                  │
          └──────────────────┴──────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Scoring Stage  │
                    │  (ECS Fargate)  │
                    │  - score.py     │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Alert Engine   │
                    │  (ECS Fargate)  │
                    │  - alerts.py    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Drift Monitor  │
                    │  (Lambda)       │
                    │  - drift.py     │
                    └─────────────────┘
```

### Component Interaction Flow

1. **EventBridge** triggers Step Functions execution (scheduled or manual)
2. **Step Functions** orchestrates pipeline stages with error handling and retries
3. **ECS Fargate** tasks execute data sync and feature engineering with shared EFS access
4. **SageMaker** training jobs run model training with spot instances
5. **S3** stores versioned model artifacts and feature snapshots
6. **ECS Fargate** tasks execute scoring and alert generation
7. **Lambda** performs drift detection and publishes metrics
8. **CloudWatch** collects logs, metrics, and triggers alarms
9. **SNS** sends notifications on failures or drift alerts



## Components and Interfaces

### 1. Pipeline Orchestrator (AWS Step Functions)

**Purpose**: Coordinate ML pipeline stages with error handling, retries, and state management.

**State Machine Definition**:
```json
{
  "Comment": "BitoGuard ML Pipeline Orchestration with SageMaker AI",
  "StartAt": "ValidateConfiguration",
  "States": {
    "ValidateConfiguration": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:bitoguard-validate-config",
      "Next": "DataSyncStage",
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "NotifyFailure"}]
    },
    "DataSyncStage": {
      "Type": "Task",
      "Resource": "arn:aws:states:::ecs:runTask.sync",
      "Parameters": {
        "LaunchType": "FARGATE",
        "Cluster": "bitoguard-ml-cluster",
        "TaskDefinition": "bitoguard-sync-task",
        "NetworkConfiguration": {...},
        "Overrides": {
          "ContainerOverrides": [{
            "Name": "sync-container",
            "Command.$": "$.syncCommand"
          }]
        }
      },
      "ResultPath": "$.syncResult",
      "Next": "PreprocessingStage",
      "Retry": [{"ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 3, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "PreprocessingStage": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sagemaker:createProcessingJob.sync",
      "Parameters": {
        "ProcessingJobName.$": "$.preprocessingJobName",
        "RoleArn": "arn:aws:iam::ACCOUNT:role/SageMakerExecutionRole",
        "ProcessingResources": {
          "ClusterConfig": {
            "InstanceType": "ml.m5.xlarge",
            "InstanceCount": 1,
            "VolumeSizeInGB": 30
          }
        },
        "AppSpecification": {
          "ImageUri": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-processing:latest"
        },
        "ProcessingInputs": [...],
        "ProcessingOutputConfig": {...},
        "StoppingCondition": {"MaxRuntimeInSeconds": 3600}
      },
      "ResultPath": "$.preprocessingResult",
      "Next": "CheckTuningEnabled",
      "Retry": [{"ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "CheckTuningEnabled": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.enableHyperparameterTuning",
          "BooleanEquals": true,
          "Next": "HyperparameterTuning"
        }
      ],
      "Default": "ParallelTraining"
    },
    "HyperparameterTuning": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sagemaker:createHyperParameterTuningJob.sync",
      "Parameters": {
        "HyperParameterTuningJobName.$": "$.tuningJobName",
        "HyperParameterTuningJobConfig": {
          "Strategy": "Bayesian",
          "HyperParameterTuningJobObjective": {
            "Type": "Maximize",
            "MetricName": "precision_at_100"
          },
          "ResourceLimits": {
            "MaxNumberOfTrainingJobs": 20,
            "MaxParallelTrainingJobs": 3
          },
          "ParameterRanges": {...}
        },
        "TrainingJobDefinition": {...}
      },
      "ResultPath": "$.tuningResult",
      "Next": "RegisterTunedModel",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "RegisterTunedModel": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:bitoguard-register-model",
      "Parameters": {
        "trainingJobName.$": "$.tuningResult.BestTrainingJob.TrainingJobName",
        "modelType": "lgbm"
      },
      "ResultPath": "$.modelRegistration",
      "Next": "ScoringStage",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "ParallelTraining": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "TrainLightGBM",
          "States": {
            "TrainLightGBM": {
              "Type": "Task",
              "Resource": "arn:aws:states:::sagemaker:createTrainingJob.sync",
              "Parameters": {
                "TrainingJobName.$": "$.lgbmJobName",
                "AlgorithmSpecification": {
                  "TrainingImage": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-training:latest",
                  "TrainingInputMode": "File"
                },
                "RoleArn": "arn:aws:iam::ACCOUNT:role/SageMakerExecutionRole",
                "ResourceConfig": {
                  "InstanceType": "ml.m5.xlarge",
                  "InstanceCount": 1,
                  "VolumeSizeInGB": 30
                },
                "StoppingCondition": {"MaxRuntimeInSeconds": 3600},
                "HyperParameters": {"model_type": "lgbm"}
              },
              "Next": "RegisterLGBMModel",
              "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "TrainingFailed"}]
            },
            "RegisterLGBMModel": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:bitoguard-register-model",
              "Parameters": {
                "trainingJobName.$": "$.TrainingJobName",
                "modelType": "lgbm"
              },
              "End": true
            },
            "TrainingFailed": {
              "Type": "Fail",
              "Error": "TrainingJobFailed",
              "Cause": "LightGBM training job failed"
            }
          }
        },
        {
          "StartAt": "TrainCatBoost",
          "States": {
            "TrainCatBoost": {
              "Type": "Task",
              "Resource": "arn:aws:states:::sagemaker:createTrainingJob.sync",
              "Parameters": {
                "TrainingJobName.$": "$.catboostJobName",
                "AlgorithmSpecification": {
                  "TrainingImage": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-training:latest",
                  "TrainingInputMode": "File"
                },
                "RoleArn": "arn:aws:iam::ACCOUNT:role/SageMakerExecutionRole",
                "ResourceConfig": {
                  "InstanceType": "ml.m5.xlarge",
                  "InstanceCount": 1,
                  "VolumeSizeInGB": 30
                },
                "StoppingCondition": {"MaxRuntimeInSeconds": 3600},
                "HyperParameters": {"model_type": "catboost"}
              },
              "Next": "RegisterCatBoostModel",
              "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "TrainingFailed"}]
            },
            "RegisterCatBoostModel": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:bitoguard-register-model",
              "Parameters": {
                "trainingJobName.$": "$.TrainingJobName",
                "modelType": "catboost"
              },
              "End": true
            },
            "TrainingFailed": {
              "Type": "Fail",
              "Error": "TrainingJobFailed",
              "Cause": "CatBoost training job failed"
            }
          }
        },
        {
          "StartAt": "TrainIsolationForest",
          "States": {
            "TrainIsolationForest": {
              "Type": "Task",
              "Resource": "arn:aws:states:::sagemaker:createTrainingJob.sync",
              "Parameters": {
                "TrainingJobName.$": "$.iforestJobName",
                "AlgorithmSpecification": {
                  "TrainingImage": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-training:latest",
                  "TrainingInputMode": "File"
                },
                "RoleArn": "arn:aws:iam::ACCOUNT:role/SageMakerExecutionRole",
                "ResourceConfig": {
                  "InstanceType": "ml.m5.large",
                  "InstanceCount": 1,
                  "VolumeSizeInGB": 20
                },
                "StoppingCondition": {"MaxRuntimeInSeconds": 1800},
                "HyperParameters": {"model_type": "iforest"}
              },
              "Next": "RegisterIForestModel",
              "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "TrainingFailed"}]
            },
            "RegisterIForestModel": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:bitoguard-register-model",
              "Parameters": {
                "trainingJobName.$": "$.TrainingJobName",
                "modelType": "iforest"
              },
              "End": true
            },
            "TrainingFailed": {
              "Type": "Fail",
              "Error": "TrainingJobFailed",
              "Cause": "IsolationForest training job failed"
            }
          }
        }
      ],
      "ResultPath": "$.trainingResults",
      "Next": "ChooseScoringMethod",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "ChooseScoringMethod": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.useBatchTransform",
          "BooleanEquals": true,
          "Next": "BatchTransformScoring"
        }
      ],
      "Default": "ScoringStage"
    },
    "BatchTransformScoring": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sagemaker:createTransformJob.sync",
      "Parameters": {
        "TransformJobName.$": "$.batchTransformJobName",
        "ModelName": "bitoguard-lgbm-model",
        "TransformInput": {
          "DataSource": {
            "S3DataSource": {
              "S3Uri": "s3://bitoguard-ml-artifacts/features/batch-input/",
              "S3DataType": "S3Prefix"
            }
          },
          "ContentType": "application/x-parquet"
        },
        "TransformOutput": {
          "S3OutputPath": "s3://bitoguard-ml-artifacts/batch-predictions/"
        },
        "TransformResources": {
          "InstanceType": "ml.m5.xlarge",
          "InstanceCount": 1
        }
      },
      "ResultPath": "$.batchTransformResult",
      "Next": "ProcessBatchResults",
      "Retry": [{"ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 2}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "ProcessBatchResults": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:bitoguard-process-batch-results",
      "ResultPath": "$.scoringResult",
      "Next": "DriftDetection",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "ScoringStage": {
      "Type": "Task",
      "Resource": "arn:aws:states:::ecs:runTask.sync",
      "Parameters": {
        "LaunchType": "FARGATE",
        "Cluster": "bitoguard-ml-cluster",
        "TaskDefinition": "bitoguard-scoring-task",
        "NetworkConfiguration": {...}
      },
      "ResultPath": "$.scoringResult",
      "Next": "DriftDetection",
      "Retry": [{"ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "DriftDetection": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:bitoguard-drift-detector",
      "ResultPath": "$.driftResult",
      "Next": "PublishMetrics",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}]
    },
    "PublishMetrics": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:cloudwatch:putMetricData",
      "Parameters": {
        "Namespace": "BitoGuard/MLPipeline",
        "MetricData": [
          {
            "MetricName": "PipelineExecutionTime",
            "Value.$": "$.executionTime",
            "Unit": "Seconds"
          },
          {
            "MetricName": "AlertCount",
            "Value.$": "$.scoringResult.alertCount",
            "Unit": "Count"
          }
        ]
      },
      "Next": "NotifySuccess"
    },
    "NotifySuccess": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:REGION:ACCOUNT:bitoguard-ml-pipeline-notifications",
        "Subject": "BitoGuard ML Pipeline - Success",
        "Message.$": "$.executionSummary"
      },
      "End": true
    },
    "NotifyFailure": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:REGION:ACCOUNT:bitoguard-ml-pipeline-notifications",
        "Subject": "BitoGuard ML Pipeline - FAILURE",
        "Message.$": "$.error"
      },
      "End": true
    }
  }
}
```

**Input Schema**:
```json
{
  "executionType": "full|incremental",
  "syncCommand": ["python", "-m", "pipeline.sync", "--full"],
  "lgbmJobName": "bitoguard-lgbm-20260315-120000",
  "catboostJobName": "bitoguard-catboost-20260315-120000",
  "iforestJobName": "bitoguard-iforest-20260315-120000",
  "configVersion": "v1.2.3"
}
```

**Output Schema**:
```json
{
  "executionId": "exec_abc123",
  "status": "SUCCEEDED|FAILED",
  "syncResult": {"rowsProcessed": 150000, "duration": 180},
  "featuresResult": {"userCount": 5000, "featureCount": 155},
  "trainingResults": [
    {"model": "lgbm", "version": "lgbm_20260315T120000Z", "metrics": {...}},
    {"model": "catboost", "version": "catboost_20260315T120000Z", "metrics": {...}},
    {"model": "iforest", "version": "iforest_20260315T120000Z", "metrics": {...}}
  ],
  "scoringResult": {"alertCount": 23, "highRiskUsers": 12},
  "driftResult": {"featureDrift": 0.08, "predictionDrift": 0.05},
  "executionTime": 1850
}
```

### 2. Scheduler (AWS EventBridge)

**Purpose**: Trigger pipeline executions on schedules and events.

**Rule Definitions**:

```python
# Daily full pipeline (2 AM UTC)
{
  "Name": "bitoguard-daily-full-pipeline",
  "ScheduleExpression": "cron(0 2 * * ? *)",
  "State": "ENABLED",
  "Targets": [{
    "Arn": "arn:aws:states:REGION:ACCOUNT:stateMachine:bitoguard-ml-pipeline",
    "RoleArn": "arn:aws:iam::ACCOUNT:role/EventBridgeStepFunctionsRole",
    "Input": json.dumps({
      "executionType": "full",
      "syncCommand": ["python", "-m", "pipeline.sync", "--full"],
      "lgbmJobName": f"bitoguard-lgbm-{timestamp}",
      "catboostJobName": f"bitoguard-catboost-{timestamp}",
      "iforestJobName": f"bitoguard-iforest-{timestamp}"
    })
  }]
}

# Incremental refresh (every 4 hours, 8 AM - 8 PM UTC)
{
  "Name": "bitoguard-incremental-refresh",
  "ScheduleExpression": "cron(0 8,12,16,20 * * ? *)",
  "State": "ENABLED",
  "Targets": [{
    "Arn": "arn:aws:states:REGION:ACCOUNT:stateMachine:bitoguard-ml-pipeline",
    "RoleArn": "arn:aws:iam::ACCOUNT:role/EventBridgeStepFunctionsRole",
    "Input": json.dumps({
      "executionType": "incremental",
      "syncCommand": ["python", "-m", "pipeline.refresh_live"],
      "skipTraining": true
    })
  }]
}
```

**Manual Trigger API**:
```python
# Lambda function for API-triggered execution
import boto3
import json
from datetime import datetime

def lambda_handler(event, context):
    sfn = boto3.client('stepfunctions')
    
    execution_input = {
        "executionType": event.get("executionType", "full"),
        "syncCommand": event.get("syncCommand", ["python", "-m", "pipeline.sync", "--full"]),
        "lgbmJobName": f"bitoguard-lgbm-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        "catboostJobName": f"bitoguard-catboost-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        "iforestJobName": f"bitoguard-iforest-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    }
    
    response = sfn.start_execution(
        stateMachineArn='arn:aws:states:REGION:ACCOUNT:stateMachine:bitoguard-ml-pipeline',
        name=f"manual-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        input=json.dumps(execution_input)
    )
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "executionArn": response["executionArn"],
            "startDate": response["startDate"].isoformat()
        })
    }
```



### 3. Training Service (AWS SageMaker)

**Purpose**: Execute model training with managed compute and spot instances.

**Training Container**:
```dockerfile
# Dockerfile.training
FROM python:3.11-slim

WORKDIR /opt/ml/code

# Install dependencies
COPY bitoguard_core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy training code
COPY bitoguard_core/ .

# SageMaker entry point
ENV PYTHONPATH=/opt/ml/code
ENV SAGEMAKER_PROGRAM=train_entrypoint.py

ENTRYPOINT ["python", "train_entrypoint.py"]
```

**Training Entry Point**:
```python
# train_entrypoint.py
import os
import json
import argparse
from pathlib import Path
from models.train import train_model
from models.train_catboost import train_catboost
from models.anomaly import train_anomaly

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model_type', type=str, required=True, choices=['lgbm', 'catboost', 'iforest'])
    parser.add_argument('--input_data', type=str, default='/opt/ml/input/data/training')
    parser.add_argument('--model_dir', type=str, default='/opt/ml/model')
    parser.add_argument('--output_data', type=str, default='/opt/ml/output')
    args = parser.parse_args()
    
    # Load feature data from S3 (mounted by SageMaker)
    feature_path = Path(args.input_data) / 'features.parquet'
    
    # Train model based on type
    if args.model_type == 'lgbm':
        result = train_model()
    elif args.model_type == 'catboost':
        result = train_catboost()
    elif args.model_type == 'iforest':
        result = train_anomaly()
    
    # Save model artifacts to /opt/ml/model (uploaded to S3 by SageMaker)
    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy trained model files
    for artifact_file in Path('artifacts/models').glob(f"{args.model_type}_*"):
        shutil.copy(artifact_file, model_dir / artifact_file.name)
    
    # Write training metadata
    metadata = {
        "model_type": args.model_type,
        "model_version": result["model_version"],
        "training_date": datetime.utcnow().isoformat(),
        "sagemaker_job": os.environ.get('TRAINING_JOB_NAME', 'local')
    }
    (model_dir / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    
    print(f"Training complete: {result}")

if __name__ == '__main__':
    main()
```

**SageMaker Training Job Configuration**:
```python
# Training job parameters
training_job_config = {
    "LightGBM": {
        "InstanceType": "ml.m5.xlarge",
        "InstanceCount": 1,
        "VolumeSizeInGB": 30,
        "MaxRuntimeInSeconds": 3600,
        "UseSpotInstances": True,
        "MaxWaitTimeInSeconds": 7200,
        "CheckpointConfig": {
            "S3Uri": "s3://bitoguard-ml-artifacts/checkpoints/lgbm"
        }
    },
    "CatBoost": {
        "InstanceType": "ml.m5.xlarge",
        "InstanceCount": 1,
        "VolumeSizeInGB": 30,
        "MaxRuntimeInSeconds": 3600,
        "UseSpotInstances": True,
        "MaxWaitTimeInSeconds": 7200
    },
    "IsolationForest": {
        "InstanceType": "ml.m5.large",
        "InstanceCount": 1,
        "VolumeSizeInGB": 20,
        "MaxRuntimeInSeconds": 1800,
        "UseSpotInstances": True,
        "MaxWaitTimeInSeconds": 3600
    }
}
```

**Input/Output Channels**:
```python
# Input: Feature data from S3
input_channels = {
    "training": {
        "S3DataSource": {
            "S3Uri": "s3://bitoguard-ml-artifacts/features/latest/",
            "S3DataType": "S3Prefix",
            "S3DataDistributionType": "FullyReplicated"
        },
        "ContentType": "application/x-parquet"
    }
}

# Output: Model artifacts to S3
output_config = {
    "S3OutputPath": "s3://bitoguard-ml-artifacts/models/"
}
```

### 4. Model Registry (S3)

**Purpose**: Version and store trained model artifacts with metadata.

**S3 Bucket Structure**:
```
s3://bitoguard-ml-artifacts/
├── models/
│   ├── lgbm/
│   │   ├── lgbm_20260315T120000Z/
│   │   │   ├── model.lgbm
│   │   │   ├── metadata.json
│   │   │   └── feature_importance.json
│   │   ├── lgbm_20260314T120000Z/
│   │   └── manifest.json
│   ├── catboost/
│   │   ├── catboost_20260315T120000Z/
│   │   │   ├── model.cbm
│   │   │   ├── metadata.json
│   │   │   └── training_log.json
│   │   └── manifest.json
│   ├── iforest/
│   │   ├── iforest_20260315T120000Z/
│   │   │   ├── model.joblib
│   │   │   └── metadata.json
│   │   └── manifest.json
│   └── stacker/
│       ├── stacker_20260315T120000Z/
│       │   ├── model.joblib
│       │   └── metadata.json
│       └── manifest.json
├── features/
│   ├── snapshots/
│   │   ├── date=2026-03-15/
│   │   │   └── features.parquet
│   │   ├── date=2026-03-14/
│   │   └── _metadata.json
│   └── latest/ -> snapshots/date=2026-03-15/
└── drift_reports/
    ├── drift_20260315T120000Z.json
    └── drift_20260314T120000Z.json
```

**Metadata Schema**:
```json
{
  "model_version": "lgbm_20260315T120000Z",
  "model_type": "lgbm",
  "training_date": "2026-03-15T12:00:00Z",
  "sagemaker_job": "bitoguard-lgbm-20260315-120000",
  "feature_columns": ["fiat_in_30d", "crypto_withdraw_30d", ...],
  "encoded_columns": ["fiat_in_30d", "crypto_withdraw_30d", ...],
  "hyperparameters": {
    "n_estimators": 250,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "subsample": 0.9,
    "colsample_bytree": 0.9
  },
  "training_metrics": {
    "train_logloss": 0.234,
    "valid_logloss": 0.267,
    "precision_at_100": 0.82
  },
  "feature_importance": {
    "fiat_in_30d": 0.156,
    "crypto_withdraw_30d": 0.143,
    "fan_out_ratio": 0.089
  },
  "data_splits": {
    "train_dates": ["2026-01-01", "2026-02-28"],
    "valid_dates": ["2026-03-01", "2026-03-07"],
    "holdout_dates": ["2026-03-08", "2026-03-14"]
  },
  "artifact_size_bytes": 2456789,
  "s3_uri": "s3://bitoguard-ml-artifacts/models/lgbm/lgbm_20260315T120000Z/"
}
```

**Manifest File**:
```json
{
  "model_type": "lgbm",
  "latest_version": "lgbm_20260315T120000Z",
  "versions": [
    {
      "version": "lgbm_20260315T120000Z",
      "created_at": "2026-03-15T12:00:00Z",
      "status": "active",
      "storage_class": "STANDARD"
    },
    {
      "version": "lgbm_20260314T120000Z",
      "created_at": "2026-03-14T12:00:00Z",
      "status": "active",
      "storage_class": "STANDARD"
    },
    {
      "version": "lgbm_20260313T120000Z",
      "created_at": "2026-03-13T12:00:00Z",
      "status": "archived",
      "storage_class": "GLACIER"
    }
  ]
}
```

**Lifecycle Policy**:
```json
{
  "Rules": [
    {
      "Id": "ArchiveOldModels",
      "Status": "Enabled",
      "Filter": {"Prefix": "models/"},
      "Transitions": [
        {
          "Days": 90,
          "StorageClass": "GLACIER"
        }
      ],
      "NoncurrentVersionTransitions": [
        {
          "NoncurrentDays": 30,
          "StorageClass": "GLACIER"
        }
      ]
    },
    {
      "Id": "RetainRecentModels",
      "Status": "Enabled",
      "Filter": {"Prefix": "models/"},
      "NoncurrentVersionExpiration": {
        "NewerNoncurrentVersions": 10,
        "NoncurrentDays": 90
      }
    }
  ]
}
```

### 5. Feature Store (S3)

**Purpose**: Store computed feature snapshots in efficient columnar format.

**Feature Snapshot Schema**:
```python
# Parquet schema for feature snapshots
feature_snapshot_schema = {
    "user_id": "string",
    "snapshot_date": "date",
    "snapshot_time": "timestamp",
    
    # Profile features
    "account_age_days": "int32",
    "kyc_level": "int8",
    "monthly_income_twd": "float64",
    
    # Transaction features (v2)
    "twd_dep_count": "int32",
    "twd_dep_sum": "float64",
    "twd_wdr_count": "int32",
    "twd_wdr_sum": "float64",
    "crypto_dep_count": "int32",
    "crypto_wdr_count": "int32",
    "crypto_wdr_twd_sum": "float64",
    
    # Velocity features
    "fiat_dep_to_swap_buy_within_1h": "int32",
    "fiat_dep_to_swap_buy_within_24h": "int32",
    
    # Graph features
    "ip_n_entities": "int32",
    "bank_n_entities": "int32",
    "wallet_n_entities": "int32",
    "blacklist_1hop_count": "int32",
    "blacklist_2hop_count": "int32",
    
    # ... (155 total columns)
}
```

**Partitioning Strategy**:
```python
# Partition by snapshot_date for efficient querying
partition_cols = ["snapshot_date"]

# Write features to S3
df.to_parquet(
    "s3://bitoguard-ml-artifacts/features/snapshots/",
    partition_cols=partition_cols,
    compression="snappy",
    engine="pyarrow",
    index=False
)
```

**Feature Metadata**:
```json
{
  "snapshot_date": "2026-03-15",
  "snapshot_time": "2026-03-15T12:30:00Z",
  "user_count": 5234,
  "feature_count": 155,
  "feature_version": "v2",
  "computation_duration_seconds": 420,
  "data_quality": {
    "null_percentage": 0.02,
    "duplicate_users": 0,
    "feature_completeness": 0.98
  },
  "feature_columns": [
    "user_id", "snapshot_date", "account_age_days", ...
  ],
  "s3_uri": "s3://bitoguard-ml-artifacts/features/snapshots/date=2026-03-15/",
  "file_size_bytes": 12456789,
  "row_group_count": 8
}
```



### 6. Pipeline Execution Tasks (ECS Fargate)

**Purpose**: Execute data sync, feature engineering, and scoring stages.

**Task Definitions**:

```python
# Data Sync Task
sync_task_definition = {
    "family": "bitoguard-sync-task",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "1024",  # 1 vCPU
    "memory": "2048",  # 2 GB
    "executionRoleArn": "arn:aws:iam::ACCOUNT:role/ECSTaskExecutionRole",
    "taskRoleArn": "arn:aws:iam::ACCOUNT:role/BitoGuardMLTaskRole",
    "containerDefinitions": [{
        "name": "sync-container",
        "image": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-core:latest",
        "command": ["python", "-m", "pipeline.sync", "--full"],
        "environment": [
            {"name": "PYTHONPATH", "value": "."},
            {"name": "BITOGUARD_SOURCE_URL", "value": "https://aws-event-api.bitopro.com"}
        ],
        "secrets": [
            {"name": "BITOGUARD_API_KEY", "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:bitoguard/api-key"}
        ],
        "mountPoints": [{
            "sourceVolume": "efs-storage",
            "containerPath": "/opt/ml/artifacts",
            "readOnly": false
        }],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": "/ecs/bitoguard-ml-pipeline",
                "awslogs-region": "REGION",
                "awslogs-stream-prefix": "sync"
            }
        }
    }],
    "volumes": [{
        "name": "efs-storage",
        "efsVolumeConfiguration": {
            "fileSystemId": "fs-12345678",
            "transitEncryption": "ENABLED",
            "authorizationConfig": {
                "iam": "ENABLED"
            }
        }
    }]
}

# Feature Engineering Task
features_task_definition = {
    "family": "bitoguard-features-task",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "2048",  # 2 vCPU
    "memory": "4096",  # 4 GB
    "executionRoleArn": "arn:aws:iam::ACCOUNT:role/ECSTaskExecutionRole",
    "taskRoleArn": "arn:aws:iam::ACCOUNT:role/BitoGuardMLTaskRole",
    "containerDefinitions": [{
        "name": "features-container",
        "image": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-core:latest",
        "command": ["python", "-m", "features.build_features_v2"],
        "environment": [
            {"name": "PYTHONPATH", "value": "."}
        ],
        "mountPoints": [{
            "sourceVolume": "efs-storage",
            "containerPath": "/opt/ml/artifacts",
            "readOnly": false
        }],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": "/ecs/bitoguard-ml-pipeline",
                "awslogs-region": "REGION",
                "awslogs-stream-prefix": "features"
            }
        }
    }],
    "volumes": [{
        "name": "efs-storage",
        "efsVolumeConfiguration": {
            "fileSystemId": "fs-12345678",
            "transitEncryption": "ENABLED",
            "authorizationConfig": {
                "iam": "ENABLED"
            }
        }
    }]
}

# Scoring Task
scoring_task_definition = {
    "family": "bitoguard-scoring-task",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "2048",  # 2 vCPU
    "memory": "4096",  # 4 GB
    "executionRoleArn": "arn:aws:iam::ACCOUNT:role/ECSTaskExecutionRole",
    "taskRoleArn": "arn:aws:iam::ACCOUNT:role/BitoGuardMLTaskRole",
    "containerDefinitions": [{
        "name": "scoring-container",
        "image": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-core:latest",
        "command": ["python", "-m", "models.score"],
        "environment": [
            {"name": "PYTHONPATH", "value": "."}
        ],
        "mountPoints": [{
            "sourceVolume": "efs-storage",
            "containerPath": "/opt/ml/artifacts",
            "readOnly": false
        }],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": "/ecs/bitoguard-ml-pipeline",
                "awslogs-region": "REGION",
                "awslogs-stream-prefix": "scoring"
            }
        }
    }],
    "volumes": [{
        "name": "efs-storage",
        "efsVolumeConfiguration": {
            "fileSystemId": "fs-12345678",
            "transitEncryption": "ENABLED",
            "authorizationConfig": {
                "iam": "ENABLED"
            }
        }
    }]
}
```

**Fargate Spot Configuration**:
```python
# Use Fargate Spot for cost savings (30-70% reduction)
capacity_provider_strategy = [
    {
        "capacityProvider": "FARGATE_SPOT",
        "weight": 70,
        "base": 0
    },
    {
        "capacityProvider": "FARGATE",
        "weight": 30,
        "base": 1  # Ensure at least 1 task on on-demand
    }
]
```

### 7. Drift Detector (AWS Lambda)

**Purpose**: Monitor feature and prediction drift between training and inference.

**Lambda Function**:
```python
# drift_detector_lambda.py
import json
import boto3
import pandas as pd
from scipy.stats import ks_2samp, chi2_contingency
import numpy as np

s3 = boto3.client('s3')
cloudwatch = boto3.client('cloudwatch')

def lambda_handler(event, context):
    """
    Detect feature and prediction drift.
    
    Input event:
    {
        "training_features_uri": "s3://bucket/features/date=2026-03-01/",
        "current_features_uri": "s3://bucket/features/date=2026-03-15/",
        "training_predictions_uri": "s3://bucket/predictions/date=2026-03-01/",
        "current_predictions_uri": "s3://bucket/predictions/date=2026-03-15/"
    }
    """
    
    # Load feature snapshots
    training_features = load_parquet_from_s3(event['training_features_uri'])
    current_features = load_parquet_from_s3(event['current_features_uri'])
    
    # Compute feature drift
    feature_drift_results = {}
    numerical_features = training_features.select_dtypes(include=[np.number]).columns
    
    for feature in numerical_features:
        if feature in current_features.columns:
            # Kolmogorov-Smirnov test for numerical features
            statistic, pvalue = ks_2samp(
                training_features[feature].dropna(),
                current_features[feature].dropna()
            )
            
            # KL divergence approximation
            kl_div = compute_kl_divergence(
                training_features[feature].dropna(),
                current_features[feature].dropna()
            )
            
            feature_drift_results[feature] = {
                "ks_statistic": float(statistic),
                "ks_pvalue": float(pvalue),
                "kl_divergence": float(kl_div),
                "drift_detected": kl_div > 0.1
            }
    
    # Compute prediction drift
    training_predictions = load_parquet_from_s3(event['training_predictions_uri'])
    current_predictions = load_parquet_from_s3(event['current_predictions_uri'])
    
    pred_drift = compute_prediction_drift(
        training_predictions['risk_score'],
        current_predictions['risk_score']
    )
    
    # Publish metrics to CloudWatch
    publish_drift_metrics(feature_drift_results, pred_drift)
    
    # Save drift report to S3
    drift_report = {
        "timestamp": event.get('timestamp', datetime.utcnow().isoformat()),
        "feature_drift": feature_drift_results,
        "prediction_drift": pred_drift,
        "drift_summary": {
            "features_with_drift": sum(1 for r in feature_drift_results.values() if r['drift_detected']),
            "total_features": len(feature_drift_results),
            "prediction_drift_percentage": pred_drift['percentage_change']
        }
    }
    
    save_drift_report(drift_report)
    
    # Trigger retraining alert if drift exceeds threshold
    if drift_report['drift_summary']['features_with_drift'] > 5 or \
       abs(pred_drift['percentage_change']) > 15:
        send_drift_alert(drift_report)
    
    return {
        "statusCode": 200,
        "body": json.dumps(drift_report['drift_summary'])
    }

def compute_kl_divergence(p_samples, q_samples, bins=50):
    """Compute KL divergence between two distributions."""
    p_hist, bin_edges = np.histogram(p_samples, bins=bins, density=True)
    q_hist, _ = np.histogram(q_samples, bins=bin_edges, density=True)
    
    # Add small epsilon to avoid log(0)
    epsilon = 1e-10
    p_hist = p_hist + epsilon
    q_hist = q_hist + epsilon
    
    # Normalize
    p_hist = p_hist / p_hist.sum()
    q_hist = q_hist / q_hist.sum()
    
    kl_div = np.sum(p_hist * np.log(p_hist / q_hist))
    return kl_div

def compute_prediction_drift(training_scores, current_scores):
    """Compute drift in prediction distributions."""
    training_mean = training_scores.mean()
    current_mean = current_scores.mean()
    percentage_change = ((current_mean - training_mean) / training_mean) * 100
    
    # Distribution comparison
    ks_stat, ks_pval = ks_2samp(training_scores, current_scores)
    
    return {
        "training_mean": float(training_mean),
        "current_mean": float(current_mean),
        "percentage_change": float(percentage_change),
        "ks_statistic": float(ks_stat),
        "ks_pvalue": float(ks_pval),
        "drift_detected": abs(percentage_change) > 15
    }

def publish_drift_metrics(feature_drift, pred_drift):
    """Publish drift metrics to CloudWatch."""
    metrics = []
    
    # Feature drift metrics
    features_with_drift = sum(1 for r in feature_drift.values() if r['drift_detected'])
    metrics.append({
        "MetricName": "FeatureDriftCount",
        "Value": features_with_drift,
        "Unit": "Count"
    })
    
    # Average KL divergence
    avg_kl = np.mean([r['kl_divergence'] for r in feature_drift.values()])
    metrics.append({
        "MetricName": "AverageKLDivergence",
        "Value": avg_kl,
        "Unit": "None"
    })
    
    # Prediction drift
    metrics.append({
        "MetricName": "PredictionDriftPercentage",
        "Value": abs(pred_drift['percentage_change']),
        "Unit": "Percent"
    })
    
    cloudwatch.put_metric_data(
        Namespace='BitoGuard/MLPipeline',
        MetricData=metrics
    )
```

**Lambda Configuration**:
```python
lambda_config = {
    "FunctionName": "bitoguard-drift-detector",
    "Runtime": "python3.11",
    "Handler": "drift_detector_lambda.lambda_handler",
    "Role": "arn:aws:iam::ACCOUNT:role/BitoGuardDriftDetectorRole",
    "Timeout": 300,  # 5 minutes
    "MemorySize": 1024,  # 1 GB
    "Environment": {
        "Variables": {
            "DRIFT_THRESHOLD_KL": "0.1",
            "DRIFT_THRESHOLD_PRED": "15",
            "SNS_TOPIC_ARN": "arn:aws:sns:REGION:ACCOUNT:bitoguard-drift-alerts"
        }
    },
    "Layers": [
        "arn:aws:lambda:REGION:336392948345:layer:AWSSDKPandas-Python311:1"
    ]
}
```



### 8. SageMaker Processing Jobs (Data Preprocessing)

**Purpose**: Execute scalable data preprocessing and feature engineering using managed compute.

**Processing Job Configuration**:
```python
processing_job_config = {
    "ProcessingJobName": "bitoguard-preprocessing-{timestamp}",
    "RoleArn": "arn:aws:iam::ACCOUNT:role/SageMakerExecutionRole",
    "ProcessingResources": {
        "ClusterConfig": {
            "InstanceType": "ml.m5.xlarge",
            "InstanceCount": 1,
            "VolumeSizeInGB": 30
        }
    },
    "AppSpecification": {
        "ImageUri": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-processing:latest",
        "ContainerEntrypoint": ["python", "preprocessing_entrypoint.py"]
    },
    "ProcessingInputs": [
        {
            "InputName": "raw-data",
            "S3Input": {
                "S3Uri": "s3://bitoguard-ml-artifacts/raw-data/",
                "LocalPath": "/opt/ml/processing/input",
                "S3DataType": "S3Prefix",
                "S3InputMode": "File"
            }
        }
    ],
    "ProcessingOutputConfig": {
        "Outputs": [
            {
                "OutputName": "processed-features",
                "S3Output": {
                    "S3Uri": "s3://bitoguard-ml-artifacts/features/processed/",
                    "LocalPath": "/opt/ml/processing/output",
                    "S3UploadMode": "EndOfJob"
                }
            },
            {
                "OutputName": "data-quality-report",
                "S3Output": {
                    "S3Uri": "s3://bitoguard-ml-artifacts/quality-reports/",
                    "LocalPath": "/opt/ml/processing/reports",
                    "S3UploadMode": "EndOfJob"
                }
            }
        ]
    },
    "StoppingCondition": {
        "MaxRuntimeInSeconds": 3600
    }
}
```

**Processing Entry Point**:
```python
# preprocessing_entrypoint.py
import os
import sys
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/opt/ml/code')

from features.build_features_v2 import build_feature_snapshot
from db.store import Store

def generate_data_quality_report(df: pd.DataFrame) -> dict:
    """Generate data quality metrics."""
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "row_count": len(df),
        "column_count": len(df.columns),
        "null_percentages": df.isnull().mean().to_dict(),
        "duplicate_rows": df.duplicated().sum(),
        "feature_completeness": (1 - df.isnull().mean().mean()),
        "numeric_features": {
            col: {
                "mean": float(df[col].mean()),
                "std": float(df[col].std()),
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "outliers": int(((df[col] - df[col].mean()).abs() > 3 * df[col].std()).sum())
            }
            for col in df.select_dtypes(include=['number']).columns
        }
    }
    return report

def main():
    print("=" * 80)
    print("BitoGuard SageMaker Processing Job")
    print("=" * 80)
    
    # Paths
    input_path = Path("/opt/ml/processing/input")
    output_path = Path("/opt/ml/processing/output")
    reports_path = Path("/opt/ml/processing/reports")
    
    output_path.mkdir(parents=True, exist_ok=True)
    reports_path.mkdir(parents=True, exist_ok=True)
    
    # Load raw data from DuckDB or S3
    print("\nLoading raw data...")
    store = Store()
    
    # Build features using existing feature engineering modules
    print("\nBuilding features...")
    features_df = build_feature_snapshot()
    
    print(f"Generated {len(features_df)} rows with {len(features_df.columns)} features")
    
    # Generate data quality report
    print("\nGenerating data quality report...")
    quality_report = generate_data_quality_report(features_df)
    
    # Save processed features to Parquet
    output_file = output_path / "features.parquet"
    features_df.to_parquet(
        output_file,
        engine='pyarrow',
        compression='snappy',
        index=False
    )
    print(f"Saved features to {output_file}")
    
    # Save quality report
    report_file = reports_path / "data_quality_report.json"
    report_file.write_text(json.dumps(quality_report, indent=2))
    print(f"Saved quality report to {report_file}")
    
    print("\n" + "=" * 80)
    print("Processing completed successfully!")
    print("=" * 80)

if __name__ == '__main__':
    main()
```

**Integration with Step Functions**:
```json
{
  "PreprocessingStage": {
    "Type": "Task",
    "Resource": "arn:aws:states:::sagemaker:createProcessingJob.sync",
    "Parameters": {
      "ProcessingJobName.$": "$.preprocessingJobName",
      "RoleArn": "arn:aws:iam::ACCOUNT:role/SageMakerExecutionRole",
      "ProcessingResources": {
        "ClusterConfig": {
          "InstanceType": "ml.m5.xlarge",
          "InstanceCount": 1,
          "VolumeSizeInGB": 30
        }
      },
      "AppSpecification": {
        "ImageUri": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-processing:latest"
      },
      "ProcessingInputs": [...],
      "ProcessingOutputConfig": {...}
    },
    "ResultPath": "$.preprocessingResult",
    "Next": "ParallelTraining",
    "Retry": [{"ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 2}],
    "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "NotifyFailure"}]
  }
}
```

### 9. SageMaker Hyperparameter Tuning Jobs

**Purpose**: Automatically optimize model hyperparameters using Bayesian optimization.

**Tuning Job Configuration**:
```python
tuning_job_config = {
    "HyperParameterTuningJobName": "bitoguard-lgbm-tuning-{timestamp}",
    "HyperParameterTuningJobConfig": {
        "Strategy": "Bayesian",
        "HyperParameterTuningJobObjective": {
            "Type": "Maximize",
            "MetricName": "precision_at_100"
        },
        "ResourceLimits": {
            "MaxNumberOfTrainingJobs": 20,
            "MaxParallelTrainingJobs": 3
        },
        "ParameterRanges": {
            "ContinuousParameterRanges": [
                {
                    "Name": "learning_rate",
                    "MinValue": "0.01",
                    "MaxValue": "0.3",
                    "ScalingType": "Logarithmic"
                },
                {
                    "Name": "subsample",
                    "MinValue": "0.6",
                    "MaxValue": "1.0",
                    "ScalingType": "Linear"
                },
                {
                    "Name": "colsample_bytree",
                    "MinValue": "0.6",
                    "MaxValue": "1.0",
                    "ScalingType": "Linear"
                }
            ],
            "IntegerParameterRanges": [
                {
                    "Name": "num_leaves",
                    "MinValue": "20",
                    "MaxValue": "100",
                    "ScalingType": "Linear"
                },
                {
                    "Name": "n_estimators",
                    "MinValue": "100",
                    "MaxValue": "500",
                    "ScalingType": "Linear"
                },
                {
                    "Name": "min_data_in_leaf",
                    "MinValue": "10",
                    "MaxValue": "100",
                    "ScalingType": "Linear"
                }
            ]
        }
    },
    "TrainingJobDefinition": {
        "StaticHyperParameters": {
            "model_type": "lgbm",
            "objective": "binary",
            "metric": "binary_logloss"
        },
        "AlgorithmSpecification": {
            "TrainingImage": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-training:latest",
            "TrainingInputMode": "File",
            "MetricDefinitions": [
                {
                    "Name": "precision_at_100",
                    "Regex": "precision_at_100: ([0-9\\.]+)"
                },
                {
                    "Name": "validation_logloss",
                    "Regex": "valid_logloss: ([0-9\\.]+)"
                }
            ]
        },
        "RoleArn": "arn:aws:iam::ACCOUNT:role/SageMakerExecutionRole",
        "InputDataConfig": [
            {
                "ChannelName": "training",
                "DataSource": {
                    "S3DataSource": {
                        "S3Uri": "s3://bitoguard-ml-artifacts/features/processed/",
                        "S3DataType": "S3Prefix"
                    }
                },
                "ContentType": "application/x-parquet"
            }
        ],
        "OutputDataConfig": {
            "S3OutputPath": "s3://bitoguard-ml-artifacts/tuning-results/"
        },
        "ResourceConfig": {
            "InstanceType": "ml.m5.xlarge",
            "InstanceCount": 1,
            "VolumeSizeInGB": 30
        },
        "StoppingCondition": {
            "MaxRuntimeInSeconds": 3600
        }
    }
}
```

**Modified Training Script for Tuning**:
```python
# train_entrypoint.py (enhanced for hyperparameter tuning)
import argparse
import json
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model_type', type=str, required=True)
    
    # Hyperparameters to tune
    parser.add_argument('--learning_rate', type=float, default=0.05)
    parser.add_argument('--num_leaves', type=int, default=31)
    parser.add_argument('--n_estimators', type=int, default=250)
    parser.add_argument('--subsample', type=float, default=0.9)
    parser.add_argument('--colsample_bytree', type=float, default=0.9)
    parser.add_argument('--min_data_in_leaf', type=int, default=20)
    
    return parser.parse_args()

def train_with_hyperparameters(args):
    """Train model with specified hyperparameters."""
    hyperparams = {
        'learning_rate': args.learning_rate,
        'num_leaves': args.num_leaves,
        'n_estimators': args.n_estimators,
        'subsample': args.subsample,
        'colsample_bytree': args.colsample_bytree,
        'min_data_in_leaf': args.min_data_in_leaf
    }
    
    # Train model with hyperparameters
    result = train_model(hyperparams)
    
    # Print metrics in format expected by SageMaker
    print(f"precision_at_100: {result['precision_at_100']}")
    print(f"valid_logloss: {result['valid_logloss']}")
    
    return result
```

**Tuning Results Analysis**:
```python
# analyze_tuning_results.py
import boto3
import pandas as pd

def get_best_hyperparameters(tuning_job_name: str) -> dict:
    """Retrieve best hyperparameters from tuning job."""
    sagemaker = boto3.client('sagemaker')
    
    response = sagemaker.describe_hyper_parameter_tuning_job(
        HyperParameterTuningJobName=tuning_job_name
    )
    
    best_training_job = response['BestTrainingJob']['TrainingJobName']
    
    job_response = sagemaker.describe_training_job(
        TrainingJobName=best_training_job
    )
    
    return {
        'hyperparameters': job_response['HyperParameters'],
        'final_metric_value': response['BestTrainingJob']['FinalHyperParameterTuningJobObjectiveMetric']['Value'],
        'training_job_name': best_training_job
    }
```

### 10. SageMaker Model Registry

**Purpose**: Centralized model versioning, approval workflows, and lineage tracking.

**Model Package Group Creation**:
```python
model_package_groups = {
    "lgbm": {
        "ModelPackageGroupName": "bitoguard-lgbm-models",
        "ModelPackageGroupDescription": "LightGBM fraud detection models"
    },
    "catboost": {
        "ModelPackageGroupName": "bitoguard-catboost-models",
        "ModelPackageGroupDescription": "CatBoost ensemble models"
    },
    "iforest": {
        "ModelPackageGroupName": "bitoguard-iforest-models",
        "ModelPackageGroupDescription": "IsolationForest anomaly detection models"
    }
}
```

**Model Registration**:
```python
# register_model.py
import boto3
from datetime import datetime

def register_model_version(
    model_type: str,
    training_job_name: str,
    model_s3_uri: str,
    metrics: dict,
    hyperparameters: dict
) -> str:
    """Register trained model in SageMaker Model Registry."""
    sagemaker = boto3.client('sagemaker')
    
    model_package_group_name = f"bitoguard-{model_type}-models"
    
    # Create model package
    response = sagemaker.create_model_package(
        ModelPackageGroupName=model_package_group_name,
        ModelPackageDescription=f"BitoGuard {model_type} model trained on {datetime.utcnow().date()}",
        InferenceSpecification={
            "Containers": [
                {
                    "Image": "ACCOUNT.dkr.ecr.REGION.amazonaws.com/bitoguard-inference:latest",
                    "ModelDataUrl": model_s3_uri,
                    "Environment": {
                        "MODEL_TYPE": model_type
                    }
                }
            ],
            "SupportedContentTypes": ["application/json"],
            "SupportedResponseMIMETypes": ["application/json"]
        },
        ModelApprovalStatus="PendingManualApproval",
        MetadataProperties={
            "GeneratedBy": "BitoGuard ML Pipeline",
            "ProjectId": "bitoguard-aml",
            "Repository": "bitoguard"
        },
        ModelMetrics={
            "ModelQuality": {
                "Statistics": {
                    "ContentType": "application/json",
                    "S3Uri": f"s3://bitoguard-ml-artifacts/metrics/{training_job_name}/metrics.json"
                }
            }
        },
        CustomerMetadataProperties={
            "training_job": training_job_name,
            "precision_at_100": str(metrics.get('precision_at_100', 0)),
            "validation_logloss": str(metrics.get('validation_logloss', 0)),
            "hyperparameters": str(hyperparameters)
        }
    )
    
    model_package_arn = response['ModelPackageArn']
    print(f"Registered model: {model_package_arn}")
    
    return model_package_arn

def approve_model(model_package_arn: str):
    """Approve model for deployment."""
    sagemaker = boto3.client('sagemaker')
    
    sagemaker.update_model_package(
        ModelPackageArn=model_package_arn,
        ModelApprovalStatus="Approved",
        ApprovalDescription="Model approved after validation"
    )
    
    print(f"Approved model: {model_package_arn}")

def get_approved_model(model_type: str) -> str:
    """Get latest approved model for deployment."""
    sagemaker = boto3.client('sagemaker')
    
    model_package_group_name = f"bitoguard-{model_type}-models"
    
    response = sagemaker.list_model_packages(
        ModelPackageGroupName=model_package_group_name,
        ModelApprovalStatus="Approved",
        SortBy="CreationTime",
        SortOrder="Descending",
        MaxResults=1
    )
    
    if response['ModelPackageSummaryList']:
        return response['ModelPackageSummaryList'][0]['ModelPackageArn']
    
    return None
```

**Model Lineage Tracking**:
```python
def track_model_lineage(training_job_name: str, model_package_arn: str):
    """Track model lineage using SageMaker Lineage."""
    sagemaker = boto3.client('sagemaker')
    
    # Associate training job with model package
    sagemaker.add_association(
        SourceArn=f"arn:aws:sagemaker:REGION:ACCOUNT:training-job/{training_job_name}",
        DestinationArn=model_package_arn,
        AssociationType="ContributedTo"
    )
```

### 11. SageMaker Real-Time Endpoints

**Purpose**: Deploy approved models for low-latency real-time inference.

**Endpoint Configuration**:
```python
endpoint_config = {
    "EndpointConfigName": "bitoguard-lgbm-endpoint-config-{timestamp}",
    "ProductionVariants": [
        {
            "VariantName": "primary-variant",
            "ModelName": "bitoguard-lgbm-model",
            "InitialInstanceCount": 1,
            "InstanceType": "ml.t3.medium",
            "InitialVariantWeight": 1.0
        }
    ],
    "DataCaptureConfig": {
        "EnableCapture": True,
        "InitialSamplingPercentage": 100,
        "DestinationS3Uri": "s3://bitoguard-ml-artifacts/endpoint-data-capture/",
        "CaptureOptions": [
            {"CaptureMode": "Input"},
            {"CaptureMode": "Output"}
        ]
    }
}

endpoint_creation = {
    "EndpointName": "bitoguard-lgbm-endpoint",
    "EndpointConfigName": "bitoguard-lgbm-endpoint-config-{timestamp}"
}
```

**Auto-Scaling Configuration**:
```python
autoscaling_config = {
    "ServiceNamespace": "sagemaker",
    "ResourceId": "endpoint/bitoguard-lgbm-endpoint/variant/primary-variant",
    "ScalableDimension": "sagemaker:variant:DesiredInstanceCount",
    "MinCapacity": 1,
    "MaxCapacity": 3,
    "TargetTrackingScalingPolicyConfiguration": {
        "TargetValue": 70.0,
        "PredefinedMetricSpecification": {
            "PredefinedMetricType": "SageMakerVariantInvocationsPerInstance"
        },
        "ScaleInCooldown": 300,
        "ScaleOutCooldown": 60
    }
}
```

**Inference Script**:
```python
# inference.py (for SageMaker endpoint)
import json
import joblib
import numpy as np
from pathlib import Path

def model_fn(model_dir):
    """Load model from model directory."""
    model_path = Path(model_dir) / "model.lgbm"
    model = joblib.load(model_path)
    return model

def input_fn(request_body, content_type):
    """Parse input data."""
    if content_type == "application/json":
        data = json.loads(request_body)
        return np.array(data['features'])
    else:
        raise ValueError(f"Unsupported content type: {content_type}")

def predict_fn(input_data, model):
    """Run prediction."""
    predictions = model.predict_proba(input_data)[:, 1]
    return predictions

def output_fn(prediction, accept):
    """Format output."""
    if accept == "application/json":
        return json.dumps({
            'risk_scores': prediction.tolist()
        }), accept
    else:
        raise ValueError(f"Unsupported accept type: {accept}")
```

**Endpoint Invocation**:
```python
# invoke_endpoint.py
import boto3
import json

def invoke_endpoint(user_features: dict) -> float:
    """Invoke SageMaker endpoint for real-time prediction."""
    runtime = boto3.client('sagemaker-runtime')
    
    payload = json.dumps({'features': [list(user_features.values())]})
    
    response = runtime.invoke_endpoint(
        EndpointName='bitoguard-lgbm-endpoint',
        ContentType='application/json',
        Accept='application/json',
        Body=payload
    )
    
    result = json.loads(response['Body'].read())
    return result['risk_scores'][0]
```

**A/B Testing Configuration**:
```python
ab_test_config = {
    "EndpointConfigName": "bitoguard-lgbm-ab-test-config",
    "ProductionVariants": [
        {
            "VariantName": "model-v1",
            "ModelName": "bitoguard-lgbm-model-v1",
            "InitialInstanceCount": 1,
            "InstanceType": "ml.t3.medium",
            "InitialVariantWeight": 0.7  # 70% traffic
        },
        {
            "VariantName": "model-v2",
            "ModelName": "bitoguard-lgbm-model-v2",
            "InitialInstanceCount": 1,
            "InstanceType": "ml.t3.medium",
            "InitialVariantWeight": 0.3  # 30% traffic
        }
    ]
}
```

### 12. SageMaker Batch Transform Jobs

**Purpose**: Efficiently score large user populations using batch inference.

**Batch Transform Configuration**:
```python
batch_transform_config = {
    "TransformJobName": "bitoguard-batch-scoring-{timestamp}",
    "ModelName": "bitoguard-lgbm-model",
    "TransformInput": {
        "DataSource": {
            "S3DataSource": {
                "S3Uri": "s3://bitoguard-ml-artifacts/features/batch-input/",
                "S3DataType": "S3Prefix"
            }
        },
        "ContentType": "application/x-parquet",
        "SplitType": "Line",
        "CompressionType": "None"
    },
    "TransformOutput": {
        "S3OutputPath": "s3://bitoguard-ml-artifacts/batch-predictions/",
        "Accept": "application/jsonlines",
        "AssembleWith": "Line"
    },
    "TransformResources": {
        "InstanceType": "ml.m5.xlarge",
        "InstanceCount": 1
    },
    "BatchStrategy": "MultiRecord",
    "MaxPayloadInMB": 6,
    "MaxConcurrentTransforms": 4,
    "DataCaptureConfig": {
        "DestinationS3Uri": "s3://bitoguard-ml-artifacts/batch-data-capture/",
        "GenerateInferenceId": True
    }
}
```

**Batch Input Preparation**:
```python
# prepare_batch_input.py
import pandas as pd
from pathlib import Path

def prepare_batch_input(features_df: pd.DataFrame, output_path: str):
    """Prepare features for batch transform."""
    # Convert to JSON Lines format
    output_file = Path(output_path) / "batch_input.jsonl"
    
    with open(output_file, 'w') as f:
        for _, row in features_df.iterrows():
            record = {
                'user_id': row['user_id'],
                'features': row.drop('user_id').tolist()
            }
            f.write(json.dumps(record) + '\n')
    
    print(f"Prepared {len(features_df)} records for batch transform")
    return output_file
```

**Batch Transform Integration with Step Functions**:
```json
{
  "BatchScoringStage": {
    "Type": "Task",
    "Resource": "arn:aws:states:::sagemaker:createTransformJob.sync",
    "Parameters": {
      "TransformJobName.$": "$.batchTransformJobName",
      "ModelName": "bitoguard-lgbm-model",
      "TransformInput": {
        "DataSource": {
          "S3DataSource": {
            "S3Uri": "s3://bitoguard-ml-artifacts/features/batch-input/",
            "S3DataType": "S3Prefix"
          }
        },
        "ContentType": "application/x-parquet"
      },
      "TransformOutput": {
        "S3OutputPath": "s3://bitoguard-ml-artifacts/batch-predictions/"
      },
      "TransformResources": {
        "InstanceType": "ml.m5.xlarge",
        "InstanceCount": 1
      }
    },
    "ResultPath": "$.batchTransformResult",
    "Next": "ProcessBatchResults",
    "Retry": [{"ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 2}],
    "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "NotifyFailure"}]
  }
}
```

**Process Batch Results**:
```python
# process_batch_results.py
import json
import pandas as pd
from pathlib import Path

def process_batch_predictions(predictions_s3_uri: str) -> pd.DataFrame:
    """Process batch transform predictions."""
    # Download predictions from S3
    predictions = []
    
    # Read JSON Lines output
    with open('predictions.jsonl', 'r') as f:
        for line in f:
            pred = json.loads(line)
            predictions.append({
                'user_id': pred['user_id'],
                'risk_score': pred['risk_scores'][0]
            })
    
    predictions_df = pd.DataFrame(predictions)
    
    # Update DuckDB with scores
    store = Store()
    store.update_risk_scores(predictions_df)
    
    # Generate alerts for high-risk users
    high_risk_users = predictions_df[predictions_df['risk_score'] > 80]
    print(f"Generated {len(high_risk_users)} high-risk alerts")
    
    return predictions_df
```

### 13. Monitoring Service (CloudWatch)

**Purpose**: Provide comprehensive observability for ML pipeline operations.

**CloudWatch Dashboard**:
```python
dashboard_body = {
    "widgets": [
        {
            "type": "metric",
            "properties": {
                "title": "Pipeline Execution Status",
                "metrics": [
                    ["BitoGuard/MLPipeline", "PipelineExecutionSuccess", {"stat": "Sum", "color": "#2ca02c"}],
                    [".", "PipelineExecutionFailure", {"stat": "Sum", "color": "#d62728"}]
                ],
                "period": 3600,
                "region": "REGION",
                "yAxis": {"left": {"min": 0}}
            }
        },
        {
            "type": "metric",
            "properties": {
                "title": "Pipeline Stage Duration",
                "metrics": [
                    ["BitoGuard/MLPipeline", "SyncDuration", {"stat": "Average"}],
                    [".", "FeaturesDuration", {"stat": "Average"}],
                    [".", "TrainingDuration", {"stat": "Average"}],
                    [".", "ScoringDuration", {"stat": "Average"}]
                ],
                "period": 3600,
                "region": "REGION",
                "yAxis": {"left": {"label": "Seconds"}}
            }
        },
        {
            "type": "metric",
            "properties": {
                "title": "Model Training Metrics",
                "metrics": [
                    ["BitoGuard/MLPipeline", "LGBMValidationLoss", {"stat": "Average"}],
                    [".", "CatBoostValidationLoss", {"stat": "Average"}],
                    [".", "IsolationForestAnomalyScore", {"stat": "Average"}]
                ],
                "period": 3600,
                "region": "REGION"
            }
        },
        {
            "type": "metric",
            "properties": {
                "title": "Alert Generation",
                "metrics": [
                    ["BitoGuard/MLPipeline", "AlertCount", {"stat": "Sum"}],
                    [".", "HighRiskUserCount", {"stat": "Sum"}],
                    [".", "CriticalRiskUserCount", {"stat": "Sum"}]
                ],
                "period": 3600,
                "region": "REGION"
            }
        },
        {
            "type": "metric",
            "properties": {
                "title": "Feature Drift",
                "metrics": [
                    ["BitoGuard/MLPipeline", "FeatureDriftCount", {"stat": "Average"}],
                    [".", "AverageKLDivergence", {"stat": "Average"}],
                    [".", "PredictionDriftPercentage", {"stat": "Average"}]
                ],
                "period": 3600,
                "region": "REGION"
            }
        },
        {
            "type": "metric",
            "properties": {
                "title": "Resource Utilization",
                "metrics": [
                    ["AWS/ECS", "CPUUtilization", {"stat": "Average", "dimensions": {"ServiceName": "bitoguard-ml-pipeline"}}],
                    [".", "MemoryUtilization", {"stat": "Average", "dimensions": {"ServiceName": "bitoguard-ml-pipeline"}}]
                ],
                "period": 300,
                "region": "REGION"
            }
        },
        {
            "type": "log",
            "properties": {
                "title": "Recent Pipeline Errors",
                "query": "SOURCE '/ecs/bitoguard-ml-pipeline' | fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20",
                "region": "REGION"
            }
        }
    ]
}
```

**CloudWatch Alarms**:
```python
alarms = [
    {
        "AlarmName": "BitoGuard-Pipeline-Execution-Failure",
        "MetricName": "PipelineExecutionFailure",
        "Namespace": "BitoGuard/MLPipeline",
        "Statistic": "Sum",
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 1,
        "ComparisonOperator": "GreaterThanOrEqualToThreshold",
        "AlarmActions": ["arn:aws:sns:REGION:ACCOUNT:bitoguard-ml-pipeline-notifications"],
        "AlarmDescription": "Alert when ML pipeline execution fails"
    },
    {
        "AlarmName": "BitoGuard-Pipeline-Duration-High",
        "MetricName": "PipelineExecutionTime",
        "Namespace": "BitoGuard/MLPipeline",
        "Statistic": "Average",
        "Period": 3600,
        "EvaluationPeriods": 1,
        "Threshold": 7200,  # 2 hours
        "ComparisonOperator": "GreaterThanThreshold",
        "AlarmActions": ["arn:aws:sns:REGION:ACCOUNT:bitoguard-ml-pipeline-notifications"],
        "AlarmDescription": "Alert when pipeline execution exceeds 2 hours"
    },
    {
        "AlarmName": "BitoGuard-Feature-Drift-High",
        "MetricName": "FeatureDriftCount",
        "Namespace": "BitoGuard/MLPipeline",
        "Statistic": "Average",
        "Period": 3600,
        "EvaluationPeriods": 2,
        "Threshold": 5,
        "ComparisonOperator": "GreaterThanThreshold",
        "AlarmActions": ["arn:aws:sns:REGION:ACCOUNT:bitoguard-drift-alerts"],
        "AlarmDescription": "Alert when more than 5 features show drift"
    },
    {
        "AlarmName": "BitoGuard-Prediction-Drift-High",
        "MetricName": "PredictionDriftPercentage",
        "Namespace": "BitoGuard/MLPipeline",
        "Statistic": "Average",
        "Period": 3600,
        "EvaluationPeriods": 2,
        "Threshold": 15,
        "ComparisonOperator": "GreaterThanThreshold",
        "AlarmActions": ["arn:aws:sns:REGION:ACCOUNT:bitoguard-drift-alerts"],
        "AlarmDescription": "Alert when prediction distribution shifts by >15%"
    },
    {
        "AlarmName": "BitoGuard-Training-Job-Failure",
        "MetricName": "TrainingJobsFailed",
        "Namespace": "AWS/SageMaker",
        "Statistic": "Sum",
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 1,
        "ComparisonOperator": "GreaterThanOrEqualToThreshold",
        "AlarmActions": ["arn:aws:sns:REGION:ACCOUNT:bitoguard-ml-pipeline-notifications"],
        "AlarmDescription": "Alert when SageMaker training job fails"
    }
]
```

**Structured Logging Format**:
```python
# Log format for all pipeline stages
log_entry = {
    "timestamp": "2026-03-15T12:00:00Z",
    "level": "INFO",
    "stage": "sync|features|training|scoring|drift",
    "execution_id": "exec_abc123",
    "message": "Stage completed successfully",
    "metadata": {
        "duration_seconds": 180,
        "rows_processed": 150000,
        "status": "success|failure",
        "error": None
    },
    "metrics": {
        "cpu_utilization": 65.5,
        "memory_utilization": 72.3,
        "disk_io_mb": 1234
    }
}
```

### 14. Configuration Management (Systems Manager Parameter Store)

**Purpose**: Centralize pipeline configuration without code changes.

**Parameter Structure**:
```python
parameters = {
    # Pipeline scheduling
    "/bitoguard/ml-pipeline/schedule/daily-full": "cron(0 2 * * ? *)",
    "/bitoguard/ml-pipeline/schedule/incremental": "cron(0 8,12,16,20 * * ? *)",
    
    # Training hyperparameters
    "/bitoguard/ml-pipeline/training/lgbm/n_estimators": "250",
    "/bitoguard/ml-pipeline/training/lgbm/learning_rate": "0.05",
    "/bitoguard/ml-pipeline/training/lgbm/num_leaves": "31",
    "/bitoguard/ml-pipeline/training/catboost/iterations": "500",
    "/bitoguard/ml-pipeline/training/catboost/learning_rate": "0.03",
    "/bitoguard/ml-pipeline/training/iforest/n_estimators": "100",
    "/bitoguard/ml-pipeline/training/iforest/contamination": "0.1",
    
    # Alert thresholds
    "/bitoguard/ml-pipeline/scoring/alert_threshold": "80",
    "/bitoguard/ml-pipeline/scoring/high_risk_threshold": "60",
    "/bitoguard/ml-pipeline/scoring/critical_risk_threshold": "80",
    
    # Drift detection
    "/bitoguard/ml-pipeline/drift/kl_threshold": "0.1",
    "/bitoguard/ml-pipeline/drift/prediction_threshold": "15",
    
    # Resource configuration
    "/bitoguard/ml-pipeline/resources/sync/cpu": "1024",
    "/bitoguard/ml-pipeline/resources/sync/memory": "2048",
    "/bitoguard/ml-pipeline/resources/features/cpu": "2048",
    "/bitoguard/ml-pipeline/resources/features/memory": "4096",
    "/bitoguard/ml-pipeline/resources/scoring/cpu": "2048",
    "/bitoguard/ml-pipeline/resources/scoring/memory": "4096",
    
    # S3 paths
    "/bitoguard/ml-pipeline/s3/bucket": "bitoguard-ml-artifacts",
    "/bitoguard/ml-pipeline/s3/models_prefix": "models/",
    "/bitoguard/ml-pipeline/s3/features_prefix": "features/",
    "/bitoguard/ml-pipeline/s3/drift_prefix": "drift_reports/",
    
    # Notification
    "/bitoguard/ml-pipeline/notifications/sns_topic": "arn:aws:sns:REGION:ACCOUNT:bitoguard-ml-pipeline-notifications"
}
```

**Configuration Loader**:
```python
# config_loader.py
import boto3
from typing import Dict, Any

class PipelineConfig:
    def __init__(self):
        self.ssm = boto3.client('ssm')
        self._cache = {}
    
    def get_parameter(self, name: str, default: Any = None) -> str:
        """Get parameter from SSM Parameter Store with caching."""
        if name in self._cache:
            return self._cache[name]
        
        try:
            response = self.ssm.get_parameter(Name=name, WithDecryption=True)
            value = response['Parameter']['Value']
            self._cache[name] = value
            return value
        except self.ssm.exceptions.ParameterNotFound:
            if default is not None:
                return default
            raise
    
    def get_training_config(self, model_type: str) -> Dict[str, Any]:
        """Get training hyperparameters for a model type."""
        prefix = f"/bitoguard/ml-pipeline/training/{model_type}/"
        
        # Get all parameters with prefix
        response = self.ssm.get_parameters_by_path(
            Path=prefix,
            Recursive=True,
            WithDecryption=True
        )
        
        config = {}
        for param in response['Parameters']:
            key = param['Name'].replace(prefix, '')
            value = param['Value']
            
            # Type conversion
            try:
                if '.' in value:
                    config[key] = float(value)
                else:
                    config[key] = int(value)
            except ValueError:
                config[key] = value
        
        return config
    
    def validate_config(self) -> bool:
        """Validate all required parameters exist."""
        required_params = [
            "/bitoguard/ml-pipeline/s3/bucket",
            "/bitoguard/ml-pipeline/scoring/alert_threshold",
            "/bitoguard/ml-pipeline/notifications/sns_topic"
        ]
        
        for param in required_params:
            try:
                self.get_parameter(param)
            except Exception as e:
                print(f"Missing required parameter: {param}")
                return False
        
        return True
```



## Data Models

### Pipeline Execution State

```python
@dataclass
class PipelineExecution:
    """Represents a single pipeline execution."""
    execution_id: str
    execution_type: str  # "full" | "incremental"
    start_time: datetime
    end_time: Optional[datetime]
    status: str  # "RUNNING" | "SUCCEEDED" | "FAILED" | "TIMED_OUT"
    state_machine_arn: str
    
    # Stage results
    sync_result: Optional[SyncResult]
    features_result: Optional[FeaturesResult]
    training_results: List[TrainingResult]
    scoring_result: Optional[ScoringResult]
    drift_result: Optional[DriftResult]
    
    # Metadata
    config_version: str
    triggered_by: str  # "schedule" | "manual" | "event"
    error_message: Optional[str]

@dataclass
class SyncResult:
    """Data sync stage result."""
    duration_seconds: int
    rows_processed: int
    tables_updated: List[str]
    watermark_position: Optional[str]
    status: str

@dataclass
class FeaturesResult:
    """Feature engineering stage result."""
    duration_seconds: int
    user_count: int
    feature_count: int
    snapshot_date: date
    s3_uri: str
    file_size_bytes: int

@dataclass
class TrainingResult:
    """Model training stage result."""
    model_type: str  # "lgbm" | "catboost" | "iforest"
    model_version: str
    duration_seconds: int
    training_job_name: str
    instance_type: str
    spot_instance_used: bool
    
    # Metrics
    training_metrics: Dict[str, float]
    validation_metrics: Dict[str, float]
    
    # Artifacts
    model_s3_uri: str
    model_size_bytes: int
    feature_importance: Dict[str, float]

@dataclass
class ScoringResult:
    """Scoring stage result."""
    duration_seconds: int
    users_scored: int
    alert_count: int
    high_risk_count: int
    critical_risk_count: int
    model_versions_used: List[str]

@dataclass
class DriftResult:
    """Drift detection result."""
    features_with_drift: int
    total_features: int
    average_kl_divergence: float
    prediction_drift_percentage: float
    drift_detected: bool
    drift_report_s3_uri: str
```

### Model Artifact Metadata

```python
@dataclass
class ModelArtifact:
    """Metadata for a trained model artifact."""
    model_version: str
    model_type: str
    created_at: datetime
    training_job_name: str
    
    # Training configuration
    hyperparameters: Dict[str, Any]
    feature_columns: List[str]
    encoded_columns: List[str]
    
    # Data splits
    train_dates: List[date]
    valid_dates: List[date]
    holdout_dates: List[date]
    
    # Metrics
    training_metrics: Dict[str, float]
    validation_metrics: Dict[str, float]
    feature_importance: Dict[str, float]
    
    # Storage
    s3_uri: str
    artifact_size_bytes: int
    storage_class: str  # "STANDARD" | "GLACIER"
    
    # Status
    status: str  # "active" | "archived" | "deprecated"

@dataclass
class ModelRegistry:
    """Registry of all model versions."""
    model_type: str
    latest_version: str
    versions: List[ModelArtifact]
    
    def get_latest(self) -> ModelArtifact:
        """Get the latest active model."""
        return next(v for v in self.versions if v.model_version == self.latest_version)
    
    def get_version(self, version: str) -> Optional[ModelArtifact]:
        """Get a specific model version."""
        return next((v for v in self.versions if v.model_version == version), None)
```

### Feature Snapshot Metadata

```python
@dataclass
class FeatureSnapshot:
    """Metadata for a feature snapshot."""
    snapshot_date: date
    snapshot_time: datetime
    user_count: int
    feature_count: int
    feature_version: str  # "v1" | "v2"
    
    # Computation
    computation_duration_seconds: int
    computation_task_arn: str
    
    # Data quality
    null_percentage: float
    duplicate_users: int
    feature_completeness: float
    
    # Storage
    s3_uri: str
    file_size_bytes: int
    row_group_count: int
    compression: str  # "snappy"
    
    # Schema
    feature_columns: List[str]
    partition_columns: List[str]

@dataclass
class FeatureStore:
    """Feature store managing snapshots."""
    snapshots: List[FeatureSnapshot]
    latest_snapshot_date: date
    
    def get_latest(self) -> FeatureSnapshot:
        """Get the most recent feature snapshot."""
        return max(self.snapshots, key=lambda s: s.snapshot_date)
    
    def get_snapshot(self, snapshot_date: date) -> Optional[FeatureSnapshot]:
        """Get a specific snapshot by date."""
        return next((s for s in self.snapshots if s.snapshot_date == snapshot_date), None)
```

### Drift Report

```python
@dataclass
class FeatureDrift:
    """Drift metrics for a single feature."""
    feature_name: str
    ks_statistic: float
    ks_pvalue: float
    kl_divergence: float
    drift_detected: bool
    
    # Distribution statistics
    training_mean: float
    training_std: float
    current_mean: float
    current_std: float

@dataclass
class PredictionDrift:
    """Drift metrics for model predictions."""
    training_mean: float
    current_mean: float
    percentage_change: float
    ks_statistic: float
    ks_pvalue: float
    drift_detected: bool

@dataclass
class DriftReport:
    """Complete drift analysis report."""
    timestamp: datetime
    training_snapshot_date: date
    current_snapshot_date: date
    
    # Feature drift
    feature_drift: Dict[str, FeatureDrift]
    features_with_drift: int
    total_features: int
    average_kl_divergence: float
    
    # Prediction drift
    prediction_drift: PredictionDrift
    
    # Actions
    retraining_recommended: bool
    alert_sent: bool
    
    # Storage
    s3_uri: str
```

### Configuration Schema

```python
@dataclass
class PipelineConfiguration:
    """Complete pipeline configuration."""
    
    # Scheduling
    daily_full_schedule: str  # cron expression
    incremental_schedule: str  # cron expression
    
    # Training hyperparameters
    lgbm_config: Dict[str, Any]
    catboost_config: Dict[str, Any]
    iforest_config: Dict[str, Any]
    
    # Scoring thresholds
    alert_threshold: float
    high_risk_threshold: float
    critical_risk_threshold: float
    
    # Drift detection
    kl_divergence_threshold: float
    prediction_drift_threshold: float
    
    # Resource allocation
    sync_cpu: int
    sync_memory: int
    features_cpu: int
    features_memory: int
    scoring_cpu: int
    scoring_memory: int
    
    # Storage
    s3_bucket: str
    models_prefix: str
    features_prefix: str
    drift_prefix: str
    
    # Notifications
    sns_topic_arn: str
    
    def validate(self) -> bool:
        """Validate configuration values."""
        if not (0 <= self.alert_threshold <= 100):
            return False
        if not (0 <= self.kl_divergence_threshold <= 1):
            return False
        if self.sync_cpu < 256 or self.sync_memory < 512:
            return False
        return True
```

### IAM Roles and Policies

```python
# Task execution role for ECS tasks
task_execution_role_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:log-group:/ecs/bitoguard-ml-pipeline:*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "arn:aws:secretsmanager:*:*:secret:bitoguard/*"
        }
    ]
}

# Task role for ML pipeline tasks
ml_task_role_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::bitoguard-ml-artifacts",
                "arn:aws:s3:::bitoguard-ml-artifacts/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticfilesystem:ClientMount",
                "elasticfilesystem:ClientWrite",
                "elasticfilesystem:DescribeFileSystems"
            ],
            "Resource": "arn:aws:elasticfilesystem:*:*:file-system/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "ssm:GetParameter",
                "ssm:GetParameters",
                "ssm:GetParametersByPath"
            ],
            "Resource": "arn:aws:ssm:*:*:parameter/bitoguard/ml-pipeline/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricData"
            ],
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "cloudwatch:namespace": "BitoGuard/MLPipeline"
                }
            }
        }
    ]
}

# SageMaker execution role
sagemaker_execution_role_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::bitoguard-ml-artifacts",
                "arn:aws:s3:::bitoguard-ml-artifacts/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:log-group:/aws/sagemaker/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricData"
            ],
            "Resource": "*"
        }
    ]
}
```



## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property Reflection

After analyzing all acceptance criteria, I identified the following redundancies and consolidations:

**Redundancy Analysis**:
- Properties 3.1, 3.2, 3.3, 5.1, 5.2, 6.1 (resource configuration checks) can be consolidated into a single property about task definition validation
- Properties 4.2 and 5.4 (S3 path structure) can be combined into a single property about artifact organization
- Properties 1.5 and 8.5 (execution logging) overlap and can be combined
- Properties 1.6, 7.7, 8.2, 9.6 (metrics publishing) can be consolidated into a single comprehensive property
- Properties 4.3 and 5.5 (metadata completeness) follow the same pattern and can be generalized
- Properties 7.2 and 5.6 (loading latest artifacts) follow the same pattern

**Consolidated Properties**:
After reflection, I've reduced 72 testable criteria to 45 unique properties by:
- Combining resource configuration checks into validation properties
- Merging similar metadata completeness checks
- Consolidating metrics publishing into comprehensive properties
- Generalizing artifact retrieval patterns



### Property 1: Pipeline Stage Sequencing

*For any* pipeline execution, stages SHALL execute in the correct sequence (sync → features → train → score → alerts), with each stage completing before the next stage starts.

**Validates: Requirements 1.1**

### Property 2: Stage Output Propagation

*For any* pipeline execution, when a stage completes successfully, its output metadata SHALL be available as input to the next stage.

**Validates: Requirements 1.2**

### Property 3: Failure Halts Execution

*For any* pipeline execution, if a stage fails, then subsequent stages SHALL NOT execute and an SNS notification SHALL be sent.

**Validates: Requirements 1.3, 3.5, 8.4**

### Property 4: Execution History Completeness

*For any* pipeline execution, the execution record SHALL contain timestamps, durations, and status for all executed stages.

**Validates: Requirements 1.5, 8.5**

### Property 5: Metrics Publishing Completeness

*For any* completed pipeline execution, CloudWatch SHALL contain metrics for execution time, alert count, stage durations, and drift statistics.

**Validates: Requirements 1.6, 7.7, 8.2, 9.6**

### Property 6: Model Artifact Versioning

*For any* completed training job, model artifacts SHALL be stored in S3 with a version identifier following the format `{model_type}_{timestamp}`.

**Validates: Requirements 3.4**

### Property 7: Artifact Path Structure

*For any* saved artifact (model or feature), the S3 path SHALL follow the pattern `s3://bucket/{artifact_type}/{type_name}/{version}/`.

**Validates: Requirements 4.2, 5.4**

### Property 8: Metadata Completeness

*For any* saved artifact (model or feature), the metadata file SHALL contain all required fields: version, timestamp, columns, metrics, and S3 URI.

**Validates: Requirements 4.3, 5.5**

### Property 9: Manifest Update

*For any* saved model artifact, the manifest file SHALL be updated to include the new version with its metadata.

**Validates: Requirements 4.4**

### Property 10: Model Retrieval by Version

*For any* model version that exists in the registry, retrieving by version ID SHALL return the correct model artifact.

**Validates: Requirements 4.5**

### Property 11: Feature Format Validation

*For any* saved feature snapshot, the S3 object SHALL be in Parquet format with Snappy compression.

**Validates: Requirements 5.3**

### Property 12: Latest Artifact Selection

*For any* artifact type (model or feature), when loading "latest", the system SHALL select the artifact with the most recent timestamp.

**Validates: Requirements 5.6, 7.1, 7.2**

### Property 13: Incremental Sync Efficiency

*For any* incremental refresh execution, only data after the last watermark position SHALL be processed.

**Validates: Requirements 6.2**

### Property 14: Sync Table Completeness

*For any* completed sync operation, the Data_Store SHALL contain all required tables: users, login_events, fiat_transactions, crypto_transactions, trade_orders.

**Validates: Requirements 6.3**

### Property 15: Post-Sync Processing Order

*For any* completed sync operation, oracle data loading and edge reconstruction SHALL execute after sync completes.

**Validates: Requirements 6.4**

### Property 16: Retry with Exponential Backoff

*For any* sync operation that encounters API errors, the system SHALL retry up to 3 times with exponentially increasing delays.

**Validates: Requirements 6.5**

### Property 17: Sync Statistics Logging

*For any* completed sync operation, CloudWatch logs SHALL contain row counts, duration, and watermark positions.

**Validates: Requirements 6.6**

### Property 18: Scoring Completeness

*For any* scoring execution, all active users in the feature snapshot SHALL have computed risk scores.

**Validates: Requirements 7.3**

### Property 19: Alert Generation Threshold

*For any* user with a risk score exceeding the alert threshold, an alert SHALL be generated with SHAP explanations.

**Validates: Requirements 7.4**

### Property 20: Alert Report Format

*For any* generated alert, the S3 report SHALL be in JSON format and contain user_id, risk_score, contributing_factors, and timestamp.

**Validates: Requirements 7.5**

### Property 21: Risk Score Persistence

*For any* completed scoring operation, the Data_Store SHALL be updated with the computed risk scores.

**Validates: Requirements 7.6**

### Property 22: Feature Drift Detection

*For any* drift detection execution, the system SHALL compute KL divergence for numerical features and chi-square statistics for categorical features.

**Validates: Requirements 9.1, 9.2**

### Property 23: Feature Drift Alerting

*For any* feature with KL divergence exceeding 0.1, a drift warning SHALL be logged to CloudWatch.

**Validates: Requirements 9.3**

### Property 24: Prediction Drift Comparison

*For any* drift detection execution, the system SHALL compare prediction distributions between consecutive scoring runs.

**Validates: Requirements 9.4**

### Property 25: Prediction Drift Alerting

*For any* drift detection where prediction distribution changes by more than 15%, a retraining alert SHALL be triggered.

**Validates: Requirements 9.5**

### Property 26: Drift Report Persistence

*For any* drift detection execution, a drift report SHALL be saved to S3 with detailed statistics for each feature.

**Validates: Requirements 9.7**

### Property 27: Artifact Compression

*For any* model artifact uploaded to S3, the artifact SHALL be gzip-compressed.

**Validates: Requirements 10.4**

### Property 28: Cost Metrics Tracking

*For any* pipeline execution, CloudWatch SHALL contain cost metrics broken down by service and pipeline stage.

**Validates: Requirements 10.7**

### Property 29: Configuration Source

*For any* pipeline execution, configuration parameters SHALL be read from AWS Systems Manager Parameter Store.

**Validates: Requirements 11.1**

### Property 30: Dynamic Configuration

*For any* configuration parameter change in SSM, the next pipeline execution SHALL use the updated value without redeployment.

**Validates: Requirements 11.2, 11.3**

### Property 31: Configuration Validation

*For any* pipeline execution, if configuration parameters are invalid, the pipeline SHALL fail early with a clear error message before executing any stages.

**Validates: Requirements 11.4**

### Property 32: Configuration Logging

*For any* pipeline execution, CloudWatch logs SHALL contain the active configuration parameters at the start of execution.

**Validates: Requirements 11.5**

### Property 33: Secrets Management

*For any* sensitive parameter (API keys, credentials), the value SHALL be retrieved from AWS Secrets Manager, not SSM Parameter Store.

**Validates: Requirements 11.6**

### Property 34: EFS Data Accessibility

*For any* completed scoring operation, the updated risk scores in the Data_Store on EFS SHALL be accessible by ECS backend tasks.

**Validates: Requirements 12.1**

### Property 35: Schema Backward Compatibility

*For any* pipeline execution, data written to DuckDB SHALL use the same table names and column names as the existing system.

**Validates: Requirements 12.2**

### Property 36: Score Availability Notification

*For any* completed scoring operation, an SNS notification SHALL be sent to the backend API service.

**Validates: Requirements 12.3**

### Property 37: Artifact Format Compatibility

*For any* trained model, the artifact format (JSON, LGBM, PKL) SHALL match the existing format expected by the scoring code.

**Validates: Requirements 12.6**

### Property 38: Task Resource Configuration

*For any* ECS task definition, the CPU and memory allocation SHALL match the requirements specified for that pipeline stage.

**Validates: Requirements 3.1, 3.2, 3.3, 5.1, 5.2, 6.1**

### Property 39: Training Instance Configuration

*For any* SageMaker training job, the instance type SHALL match the requirements specified for that model type (ml.m5.xlarge for LightGBM/CatBoost, ml.m5.large for IsolationForest).

**Validates: Requirements 3.1, 3.2, 3.3**

### Property 40: Spot Instance Configuration

*For any* SageMaker training job, spot instances SHALL be enabled with automatic fallback to on-demand.

**Validates: Requirements 3.6, 10.1**

### Property 41: Fargate Spot Configuration

*For any* non-critical pipeline stage (sync, features), the ECS task SHALL use Fargate Spot capacity providers.

**Validates: Requirements 10.2**

### Property 42: S3 Versioning Enabled

*For any* S3 bucket storing model artifacts, versioning SHALL be enabled.

**Validates: Requirements 4.1**

### Property 43: Lifecycle Policy Configuration

*For any* S3 bucket storing model artifacts, lifecycle policies SHALL archive models older than 90 days to Glacier and retain the 10 most recent versions in Standard storage.

**Validates: Requirements 4.6, 4.7**

### Property 44: Intelligent Tiering Configuration

*For any* S3 bucket storing feature snapshots, the storage class SHALL be configured for S3 Intelligent-Tiering.

**Validates: Requirements 10.5**

### Property 45: EFS Mount Point Consistency

*For any* ML pipeline task and backend API task, both SHALL use the same EFS file system ID for shared access to the Data_Store.

**Validates: Requirements 12.5**

### Property 46: Processing Job Output Format

*For any* completed SageMaker Processing Job, the output SHALL be written to S3 in Parquet format with Snappy compression.

**Validates: Requirements 13.4**

### Property 47: Data Quality Report Completeness

*For any* completed SageMaker Processing Job, the data quality report SHALL contain null percentages, outlier counts, and feature distributions for all features.

**Validates: Requirements 13.5**

### Property 48: Processing Job Custom Script Support

*For any* preprocessing script from bitoguard_core/features module, the SageMaker Processing Job SHALL successfully execute the script and produce valid output.

**Validates: Requirements 13.7**

### Property 49: Hyperparameter Tuning Best Model Selection

*For any* completed hyperparameter tuning job, the selected best model SHALL have the highest precision@100 metric value among all training trials.

**Validates: Requirements 14.5**

### Property 50: Tuning Trial Results Persistence

*For any* completed hyperparameter tuning job, all trial results with hyperparameters and metrics SHALL be saved to S3.

**Validates: Requirements 14.6**

### Property 51: Model Registration After Training

*For any* completed training job, the trained model SHALL be registered in SageMaker Model Registry with model artifacts, metadata, and evaluation metrics.

**Validates: Requirements 15.1, 15.3**

### Property 52: Model Approval Status Enforcement

*For any* model deployment to inference endpoints, the model SHALL have Approved status in the Model Registry.

**Validates: Requirements 15.5**

### Property 53: Model Lineage Tracking

*For any* registered model, the Model Registry SHALL contain lineage information including training job name, dataset version, and hyperparameters.

**Validates: Requirements 15.6**

### Property 54: Model Version Incrementing

*For any* new model registration of the same model type, the version number SHALL be greater than all previous versions.

**Validates: Requirements 15.7**

### Property 55: Endpoint API Contract

*For any* SageMaker endpoint invocation with valid JSON input containing user features, the endpoint SHALL return a JSON response with risk score predictions.

**Validates: Requirements 16.5**

### Property 56: Endpoint Metrics Publishing

*For any* endpoint invocation, CloudWatch SHALL receive metrics for invocation latency, error rate, and throughput.

**Validates: Requirements 16.7**

### Property 57: Batch Transform Output Format

*For any* completed batch transform job, the predictions SHALL be written to S3 in JSON Lines format.

**Validates: Requirements 17.4**

### Property 58: Batch Transform Capacity

*For any* batch transform job with up to 10,000 user records, the job SHALL complete successfully without errors.

**Validates: Requirements 17.5**

### Property 59: Batch Transform Data Capture

*For any* batch transform job with data capture enabled, input features and predictions SHALL be saved to the configured S3 location.

**Validates: Requirements 17.7**



## Error Handling

### Pipeline-Level Error Handling

**State Machine Error Handling**:
- Each state in the Step Functions state machine includes `Catch` blocks to handle failures
- Failed states transition to a `NotifyFailure` state that sends SNS notifications
- Retry policies with exponential backoff for transient failures
- Maximum retry attempts: 3 for data operations, 2 for compute operations

**Error Categories**:

1. **Configuration Errors** (fail-fast):
   - Invalid parameter values in SSM Parameter Store
   - Missing required configuration
   - Invalid S3 bucket or EFS file system references
   - Action: Fail immediately before executing any stages

2. **Data Errors** (retryable):
   - API connection failures to BitoPro source
   - S3 access errors (throttling, permissions)
   - EFS mount failures
   - Action: Retry with exponential backoff (1s, 2s, 4s)

3. **Compute Errors** (retryable with limits):
   - ECS task failures (OOM, timeout)
   - SageMaker training job failures
   - Lambda function timeouts
   - Action: Retry up to 2 times, then fail

4. **Resource Errors** (non-retryable):
   - Spot instance unavailability (fallback to on-demand)
   - ECS cluster capacity issues
   - Action: Use fallback resources or fail with notification

### Stage-Specific Error Handling

**Data Sync Stage**:
```python
def sync_with_retry(max_retries=3, backoff_base=2):
    """Execute sync with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            result = run_sync()
            return result
        except APIConnectionError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = backoff_base ** attempt
            logger.warning(f"Sync failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
            time.sleep(wait_time)
        except DataValidationError as e:
            # Non-retryable error
            logger.error(f"Data validation failed: {e}")
            raise
```

**Feature Engineering Stage**:
```python
def build_features_with_validation():
    """Build features with data quality validation."""
    try:
        features = build_and_store_v2_features(...)
        
        # Validate feature quality
        if features.empty:
            raise ValueError("Feature computation produced empty dataset")
        
        null_pct = features.isnull().sum().sum() / (len(features) * len(features.columns))
        if null_pct > 0.1:
            raise ValueError(f"Feature null percentage too high: {null_pct:.2%}")
        
        return features
    except MemoryError as e:
        logger.error(f"OOM during feature computation: {e}")
        raise
    except Exception as e:
        logger.error(f"Feature computation failed: {e}")
        raise
```

**Training Stage**:
```python
def train_with_checkpointing(model_type):
    """Train model with checkpointing for spot instance interruptions."""
    checkpoint_uri = f"s3://bitoguard-ml-artifacts/checkpoints/{model_type}/"
    
    try:
        result = sagemaker_train(
            model_type=model_type,
            checkpoint_s3_uri=checkpoint_uri,
            use_spot_instances=True,
            max_wait_time=7200  # 2 hours
        )
        return result
    except SpotInstanceInterruption:
        # SageMaker automatically resumes from checkpoint
        logger.info("Spot instance interrupted, resuming from checkpoint")
        raise  # Let Step Functions retry
    except TrainingJobError as e:
        logger.error(f"Training job failed: {e}")
        # Capture training logs
        save_training_logs(e.training_job_name)
        raise
```

**Scoring Stage**:
```python
def score_with_fallback():
    """Score with fallback to previous model version if current fails."""
    try:
        # Try latest models
        result = score_latest_snapshot_v2()
        return result
    except ModelLoadError as e:
        logger.warning(f"Failed to load latest models: {e}, falling back to previous version")
        # Fallback to previous model version
        result = score_with_previous_models()
        return result
    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        raise
```

### Notification Strategy

**SNS Topics**:
- `bitoguard-ml-pipeline-notifications`: General pipeline notifications (success/failure)
- `bitoguard-drift-alerts`: Drift detection alerts requiring attention
- `bitoguard-critical-errors`: Critical errors requiring immediate action

**Notification Content**:
```json
{
  "subject": "BitoGuard ML Pipeline - FAILURE",
  "message": {
    "execution_id": "exec_abc123",
    "execution_type": "full",
    "failed_stage": "training",
    "error_type": "TrainingJobError",
    "error_message": "Training job failed: OOM during model fitting",
    "timestamp": "2026-03-15T12:30:00Z",
    "logs_url": "https://console.aws.amazon.com/cloudwatch/logs/...",
    "state_machine_url": "https://console.aws.amazon.com/states/...",
    "recommended_action": "Increase training instance memory or reduce batch size"
  }
}
```

### Monitoring and Alerting

**CloudWatch Alarms**:
- Pipeline execution failure (immediate alert)
- Pipeline duration exceeds 2 hours (warning)
- Training job failure (immediate alert)
- Feature drift exceeds threshold (warning)
- Prediction drift exceeds threshold (warning)
- ECS task OOM errors (immediate alert)

**Log Aggregation**:
- All pipeline logs centralized in `/ecs/bitoguard-ml-pipeline` log group
- Structured JSON format for easy parsing and analysis
- Log retention: 30 days
- Log insights queries for common error patterns



## Testing Strategy

### Dual Testing Approach

The testing strategy combines unit tests for specific examples and edge cases with property-based tests for universal properties across all inputs. Both approaches are complementary and necessary for comprehensive coverage.

**Unit Tests**: Focus on specific examples, integration points, and edge cases
**Property Tests**: Verify universal properties across randomized inputs (minimum 100 iterations)

### Property-Based Testing Library

**Python**: Use `hypothesis` for property-based testing
```python
pip install hypothesis
```

**Test Configuration**:
- Minimum 100 iterations per property test
- Each test tagged with feature name and property number
- Tag format: `# Feature: aws-ml-pipeline-optimization, Property {N}: {property_text}`

### Test Categories

#### 1. Pipeline Orchestration Tests

**Unit Tests**:
```python
def test_manual_pipeline_trigger():
    """Test manual pipeline triggering via API."""
    # Validates: Property 1.4 (example)
    response = trigger_pipeline_execution(execution_type="full")
    assert response["statusCode"] == 200
    assert "executionArn" in response["body"]

def test_eventbridge_schedule_configuration():
    """Test EventBridge schedule rules are configured correctly."""
    # Validates: Properties 2.1, 2.2 (examples)
    daily_rule = get_eventbridge_rule("bitoguard-daily-full-pipeline")
    assert daily_rule["ScheduleExpression"] == "cron(0 2 * * ? *)"
    
    incremental_rule = get_eventbridge_rule("bitoguard-incremental-refresh")
    assert incremental_rule["ScheduleExpression"] == "cron(0 8,12,16,20 * * ? *)"
```

**Property Tests**:
```python
from hypothesis import given, strategies as st

@given(
    stages=st.lists(
        st.sampled_from(["sync", "features", "training", "scoring", "drift"]),
        min_size=2,
        max_size=5,
        unique=True
    )
)
def test_pipeline_stage_sequencing(stages):
    """
    Feature: aws-ml-pipeline-optimization, Property 1: Pipeline Stage Sequencing
    
    For any pipeline execution, stages SHALL execute in the correct sequence,
    with each stage completing before the next stage starts.
    """
    execution = execute_pipeline_with_stages(stages)
    
    # Verify stages executed in order
    for i in range(len(stages) - 1):
        current_stage = execution.get_stage_result(stages[i])
        next_stage = execution.get_stage_result(stages[i + 1])
        
        assert current_stage.end_time <= next_stage.start_time, \
            f"Stage {stages[i]} did not complete before {stages[i + 1]} started"

@given(
    stage_outputs=st.dictionaries(
        keys=st.sampled_from(["sync", "features", "training"]),
        values=st.dictionaries(
            keys=st.sampled_from(["duration", "rows_processed", "status"]),
            values=st.one_of(st.integers(min_value=0), st.text())
        )
    )
)
def test_stage_output_propagation(stage_outputs):
    """
    Feature: aws-ml-pipeline-optimization, Property 2: Stage Output Propagation
    
    For any pipeline execution, when a stage completes successfully,
    its output metadata SHALL be available as input to the next stage.
    """
    execution = create_pipeline_execution()
    
    for stage_name, output_data in stage_outputs.items():
        execution.complete_stage(stage_name, output_data)
        next_stage = execution.get_next_stage(stage_name)
        
        if next_stage:
            next_stage_input = execution.get_stage_input(next_stage)
            assert stage_name in next_stage_input, \
                f"Output from {stage_name} not available to {next_stage}"
            assert next_stage_input[stage_name] == output_data

@given(
    failing_stage=st.sampled_from(["sync", "features", "training", "scoring"])
)
def test_failure_halts_execution(failing_stage):
    """
    Feature: aws-ml-pipeline-optimization, Property 3: Failure Halts Execution
    
    For any pipeline execution, if a stage fails, then subsequent stages
    SHALL NOT execute and an SNS notification SHALL be sent.
    """
    execution = create_pipeline_execution()
    execution.inject_failure(failing_stage)
    
    result = execution.run()
    
    # Verify subsequent stages did not execute
    stage_order = ["sync", "features", "training", "scoring", "drift"]
    failing_index = stage_order.index(failing_stage)
    
    for subsequent_stage in stage_order[failing_index + 1:]:
        assert not execution.stage_executed(subsequent_stage), \
            f"Stage {subsequent_stage} executed after {failing_stage} failed"
    
    # Verify SNS notification sent
    notifications = get_sns_notifications()
    assert any(n["subject"].contains("FAILURE") for n in notifications)
```



#### 2. Model Artifact Management Tests

**Property Tests**:
```python
@given(
    model_type=st.sampled_from(["lgbm", "catboost", "iforest"]),
    timestamp=st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2026, 12, 31))
)
def test_model_artifact_versioning(model_type, timestamp):
    """
    Feature: aws-ml-pipeline-optimization, Property 6: Model Artifact Versioning
    
    For any completed training job, model artifacts SHALL be stored in S3
    with a version identifier following the format {model_type}_{timestamp}.
    """
    training_result = complete_training_job(model_type, timestamp)
    
    expected_version = f"{model_type}_{timestamp.strftime('%Y%m%dT%H%M%SZ')}"
    assert training_result.model_version == expected_version
    
    # Verify artifact exists in S3
    s3_key = f"models/{model_type}/{expected_version}/model.{get_extension(model_type)}"
    assert s3_object_exists("bitoguard-ml-artifacts", s3_key)

@given(
    artifact_type=st.sampled_from(["models", "features"]),
    type_name=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Nd"))),
    version=st.text(min_size=10, max_size=30)
)
def test_artifact_path_structure(artifact_type, type_name, version):
    """
    Feature: aws-ml-pipeline-optimization, Property 7: Artifact Path Structure
    
    For any saved artifact (model or feature), the S3 path SHALL follow
    the pattern s3://bucket/{artifact_type}/{type_name}/{version}/.
    """
    artifact = save_artifact(artifact_type, type_name, version)
    
    expected_pattern = f"s3://bitoguard-ml-artifacts/{artifact_type}/{type_name}/{version}/"
    assert artifact.s3_uri.startswith(expected_pattern)

@given(
    artifact_data=st.fixed_dictionaries({
        "version": st.text(min_size=10),
        "timestamp": st.datetimes(),
        "columns": st.lists(st.text(min_size=1), min_size=1),
        "metrics": st.dictionaries(st.text(), st.floats(min_value=0, max_value=1)),
        "s3_uri": st.text(min_size=10)
    })
)
def test_metadata_completeness(artifact_data):
    """
    Feature: aws-ml-pipeline-optimization, Property 8: Metadata Completeness
    
    For any saved artifact (model or feature), the metadata file SHALL contain
    all required fields: version, timestamp, columns, metrics, and S3 URI.
    """
    artifact = save_artifact_with_metadata(artifact_data)
    metadata = load_metadata_from_s3(artifact.s3_uri)
    
    required_fields = ["version", "timestamp", "columns", "metrics", "s3_uri"]
    for field in required_fields:
        assert field in metadata, f"Missing required field: {field}"
        assert metadata[field] is not None

@given(
    model_versions=st.lists(
        st.fixed_dictionaries({
            "version": st.text(min_size=10),
            "timestamp": st.datetimes()
        }),
        min_size=1,
        max_size=10
    )
)
def test_manifest_update(model_versions):
    """
    Feature: aws-ml-pipeline-optimization, Property 9: Manifest Update
    
    For any saved model artifact, the manifest file SHALL be updated
    to include the new version with its metadata.
    """
    model_type = "lgbm"
    
    for version_data in model_versions:
        save_model_artifact(model_type, version_data["version"], version_data["timestamp"])
    
    manifest = load_manifest(model_type)
    
    # Verify all versions are in manifest
    manifest_versions = {v["version"] for v in manifest["versions"]}
    expected_versions = {v["version"] for v in model_versions}
    assert manifest_versions == expected_versions

@given(
    model_type=st.sampled_from(["lgbm", "catboost", "iforest"]),
    version_id=st.text(min_size=10, max_size=30)
)
def test_model_retrieval_by_version(model_type, version_id):
    """
    Feature: aws-ml-pipeline-optimization, Property 10: Model Retrieval by Version
    
    For any model version that exists in the registry, retrieving by version ID
    SHALL return the correct model artifact.
    """
    # Save model with specific version
    original_artifact = save_model_artifact(model_type, version_id)
    
    # Retrieve by version
    retrieved_artifact = retrieve_model_by_version(model_type, version_id)
    
    assert retrieved_artifact.model_version == version_id
    assert retrieved_artifact.s3_uri == original_artifact.s3_uri
```

#### 3. Feature Store Tests

**Property Tests**:
```python
@given(
    feature_data=st.data_frames([
        column("user_id", dtype=str),
        column("snapshot_date", dtype="datetime64[ns]"),
        column("feature_1", dtype=float),
        column("feature_2", dtype=float)
    ])
)
def test_feature_format_validation(feature_data):
    """
    Feature: aws-ml-pipeline-optimization, Property 11: Feature Format Validation
    
    For any saved feature snapshot, the S3 object SHALL be in Parquet format
    with Snappy compression.
    """
    snapshot = save_feature_snapshot(feature_data)
    
    # Download and inspect S3 object
    s3_object = download_s3_object(snapshot.s3_uri)
    
    # Verify Parquet format
    assert is_parquet_format(s3_object)
    
    # Verify Snappy compression
    parquet_metadata = get_parquet_metadata(s3_object)
    assert parquet_metadata["compression"] == "SNAPPY"

@given(
    artifact_type=st.sampled_from(["model", "feature"]),
    timestamps=st.lists(st.datetimes(), min_size=2, max_size=10, unique=True)
)
def test_latest_artifact_selection(artifact_type, timestamps):
    """
    Feature: aws-ml-pipeline-optimization, Property 12: Latest Artifact Selection
    
    For any artifact type (model or feature), when loading "latest",
    the system SHALL select the artifact with the most recent timestamp.
    """
    # Save artifacts with different timestamps
    for ts in timestamps:
        save_artifact_with_timestamp(artifact_type, ts)
    
    # Load latest
    latest_artifact = load_latest_artifact(artifact_type)
    
    # Verify it's the most recent
    expected_latest = max(timestamps)
    assert latest_artifact.timestamp == expected_latest
```

