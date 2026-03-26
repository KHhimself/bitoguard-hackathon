# Requirements Document

## Introduction

This document specifies requirements for optimizing BitoGuard's AWS deployment and ML operations pipeline. The system currently uses manual processes for model training (via `make train`) and data pipeline execution. This feature will automate and optimize these operations using AWS-native services including SageMaker, Step Functions, EventBridge, S3, and CloudWatch, while maintaining the existing ECS Fargate deployment for the API services.

## Glossary

- **ML_Pipeline**: The complete machine learning workflow including data sync, feature engineering, model training, scoring, and alert generation
- **Pipeline_Orchestrator**: AWS Step Functions state machine coordinating ML pipeline stages
- **Model_Registry**: S3-based storage system for versioned model artifacts with metadata
- **Training_Service**: AWS SageMaker training jobs for LightGBM, CatBoost, and IsolationForest models
- **Scheduler**: AWS EventBridge rules triggering pipeline execution on schedules or events
- **Data_Store**: DuckDB database persisted on EFS, accessed by pipeline stages
- **Feature_Store**: S3-based storage for computed feature snapshots
- **Monitoring_Service**: CloudWatch dashboards and alarms tracking ML operations health
- **Artifact_Manager**: Service managing model artifacts, feature snapshots, and training metadata
- **Pipeline_Stage**: Individual step in ML workflow (sync, features, train, score, alerts)
- **Execution_Environment**: ECS Fargate tasks or Lambda functions running pipeline code
- **Drift_Detector**: Service monitoring feature and model drift between training and inference

## Requirements

### Requirement 1: Automated Pipeline Orchestration

**User Story:** As a data scientist, I want the ML pipeline to execute automatically on a schedule, so that models stay current without manual intervention

#### Acceptance Criteria

1. THE Pipeline_Orchestrator SHALL execute the complete ML_Pipeline in sequence: sync → features → train → score → alerts
2. WHEN a pipeline stage completes successfully, THE Pipeline_Orchestrator SHALL pass output metadata to the next stage
3. IF a pipeline stage fails, THEN THE Pipeline_Orchestrator SHALL halt execution and send failure notifications via SNS
4. THE Pipeline_Orchestrator SHALL support manual triggering via API or console
5. THE Pipeline_Orchestrator SHALL record execution history with timestamps, durations, and status for each stage
6. WHEN the pipeline completes, THE Pipeline_Orchestrator SHALL publish success metrics to CloudWatch

### Requirement 2: Scheduled Pipeline Execution

**User Story:** As an operations engineer, I want pipelines to run on configurable schedules, so that I can balance freshness with cost

#### Acceptance Criteria

1. THE Scheduler SHALL trigger full pipeline execution daily at a configurable time
2. THE Scheduler SHALL trigger incremental refresh every 4 hours during business hours
3. WHERE manual override is needed, THE Scheduler SHALL support one-time schedule adjustments via API
4. THE Scheduler SHALL support event-driven triggers when new data arrives in source systems
5. WHEN a scheduled execution is missed due to system issues, THE Scheduler SHALL log the missed execution and alert operators

### Requirement 3: Model Training Automation

**User Story:** As a data scientist, I want model training to run automatically with proper resource allocation, so that I don't need to manually execute `make train`

#### Acceptance Criteria

1. THE Training_Service SHALL train LightGBM classifier using ml.m5.xlarge instances with 4 vCPU and 16GB RAM
2. THE Training_Service SHALL train IsolationForest anomaly detector using ml.m5.large instances with 2 vCPU and 8GB RAM
3. THE Training_Service SHALL train CatBoost ensemble model using ml.m5.xlarge instances with 4 vCPU and 16GB RAM
4. WHEN training completes, THE Training_Service SHALL save model artifacts to the Model_Registry with version timestamps
5. WHEN training fails, THE Training_Service SHALL capture error logs and send alerts via SNS
6. THE Training_Service SHALL use spot instances when available to reduce training costs by up to 70%
7. THE Training_Service SHALL terminate compute resources immediately after training completes

### Requirement 4: Model Artifact Management

**User Story:** As a data scientist, I want model artifacts versioned and stored reliably, so that I can track model lineage and rollback if needed

#### Acceptance Criteria

1. THE Model_Registry SHALL store model artifacts in S3 with versioning enabled
2. THE Model_Registry SHALL organize artifacts by model type and timestamp: `s3://bucket/models/{model_type}/{version}/`
3. WHEN a model is saved, THE Artifact_Manager SHALL store metadata including training date, feature columns, hyperparameters, and validation metrics
4. THE Artifact_Manager SHALL maintain a manifest file listing all available model versions with their metadata
5. THE Artifact_Manager SHALL support retrieval of specific model versions by timestamp or version ID
6. THE Artifact_Manager SHALL apply lifecycle policies to archive models older than 90 days to S3 Glacier
7. THE Artifact_Manager SHALL retain the 10 most recent model versions in S3 Standard storage class

### Requirement 5: Feature Engineering Automation

**User Story:** As a data scientist, I want feature snapshots computed automatically and stored efficiently, so that training and scoring use consistent features

#### Acceptance Criteria

1. THE ML_Pipeline SHALL execute graph feature computation using NetworkX on ECS Fargate tasks with 2 vCPU and 4GB RAM
2. THE ML_Pipeline SHALL execute statistical feature computation using pandas on ECS Fargate tasks with 2 vCPU and 4GB RAM
3. WHEN feature computation completes, THE Feature_Store SHALL save feature snapshots to S3 in Parquet format with Snappy compression
4. THE Feature_Store SHALL partition feature snapshots by snapshot_date for efficient querying
5. THE Feature_Store SHALL maintain feature metadata including column names, data types, and computation timestamps
6. WHEN scoring requires features, THE ML_Pipeline SHALL load the most recent feature snapshot from the Feature_Store

### Requirement 6: Data Pipeline Execution

**User Story:** As an operations engineer, I want data sync and normalization to run reliably, so that the ML pipeline has fresh data

#### Acceptance Criteria

1. THE ML_Pipeline SHALL execute full data sync from BitoPro API using ECS Fargate tasks with 1 vCPU and 2GB RAM
2. THE ML_Pipeline SHALL execute incremental refresh using watermark-based checkpointing for efficiency
3. WHEN sync completes, THE Data_Store SHALL contain normalized tables: users, login_events, fiat_transactions, crypto_transactions, trade_orders
4. THE ML_Pipeline SHALL execute oracle data loading and edge reconstruction after sync completes
5. IF sync fails due to API errors, THEN THE ML_Pipeline SHALL retry up to 3 times with exponential backoff
6. THE ML_Pipeline SHALL log sync statistics including row counts, duration, and watermark positions to CloudWatch

### Requirement 7: Scoring and Alert Generation

**User Story:** As a compliance officer, I want risk scores and alerts generated automatically after model training, so that I can review suspicious activity promptly

#### Acceptance Criteria

1. WHEN model training completes, THE ML_Pipeline SHALL execute scoring on the latest feature snapshot
2. THE ML_Pipeline SHALL load the most recent trained models from the Model_Registry for scoring
3. THE ML_Pipeline SHALL compute risk scores for all active users using the loaded models
4. WHEN a user's risk score exceeds the alert threshold, THE ML_Pipeline SHALL generate an alert with SHAP explanations
5. THE ML_Pipeline SHALL save alert reports to S3 with JSON format including user_id, risk_score, contributing_factors, and timestamp
6. THE ML_Pipeline SHALL update the Data_Store with computed risk scores for API access
7. WHEN scoring completes, THE ML_Pipeline SHALL publish alert count metrics to CloudWatch

### Requirement 8: Pipeline Monitoring and Observability

**User Story:** As an operations engineer, I want comprehensive monitoring of pipeline health, so that I can detect and resolve issues quickly

#### Acceptance Criteria

1. THE Monitoring_Service SHALL create CloudWatch dashboards displaying pipeline execution status, duration, and success rate
2. THE Monitoring_Service SHALL track metrics for each Pipeline_Stage including execution time, memory usage, and error rate
3. WHEN pipeline execution time exceeds 2 hours, THE Monitoring_Service SHALL trigger a CloudWatch alarm
4. WHEN any Pipeline_Stage fails, THE Monitoring_Service SHALL send SNS notifications to the operations team
5. THE Monitoring_Service SHALL log all pipeline executions with structured JSON logs including stage, status, duration, and error messages
6. THE Monitoring_Service SHALL retain logs for 30 days in CloudWatch Logs
7. THE Monitoring_Service SHALL track model training metrics including training loss, validation metrics, and feature importance

### Requirement 9: Feature and Model Drift Detection

**User Story:** As a data scientist, I want automatic drift detection, so that I know when models need retraining

#### Acceptance Criteria

1. WHEN scoring completes, THE Drift_Detector SHALL compare current feature distributions to training feature distributions
2. THE Drift_Detector SHALL compute KL divergence for numerical features and chi-square statistics for categorical features
3. IF feature drift exceeds threshold (KL divergence > 0.1), THEN THE Drift_Detector SHALL log a drift warning to CloudWatch
4. THE Drift_Detector SHALL compare model prediction distributions between consecutive scoring runs
5. IF prediction drift exceeds threshold (>15% change in score distribution), THEN THE Drift_Detector SHALL trigger a retraining alert
6. THE Drift_Detector SHALL publish drift metrics to CloudWatch for dashboard visualization
7. THE Drift_Detector SHALL save drift reports to S3 with detailed statistics for each feature

### Requirement 10: Cost Optimization and Resource Management

**User Story:** As a platform engineer, I want efficient resource utilization, so that ML operations remain cost-effective

#### Acceptance Criteria

1. THE Training_Service SHALL use spot instances for training jobs with automatic fallback to on-demand if spot unavailable
2. THE ML_Pipeline SHALL use ECS Fargate Spot capacity for non-critical pipeline stages (features, sync)
3. THE ML_Pipeline SHALL scale ECS task CPU and memory based on pipeline stage requirements
4. THE Artifact_Manager SHALL compress model artifacts using gzip before uploading to S3
5. THE Feature_Store SHALL use S3 Intelligent-Tiering for automatic cost optimization of feature snapshots
6. THE ML_Pipeline SHALL terminate all compute resources within 5 minutes of stage completion
7. THE Monitoring_Service SHALL track and report monthly ML operations costs by service and pipeline stage

### Requirement 11: Pipeline Configuration Management

**User Story:** As a data scientist, I want to configure pipeline parameters without code changes, so that I can experiment with different settings

#### Acceptance Criteria

1. THE ML_Pipeline SHALL read configuration from AWS Systems Manager Parameter Store
2. THE ML_Pipeline SHALL support configurable parameters including training hyperparameters, alert thresholds, and schedule intervals
3. WHEN configuration changes, THE ML_Pipeline SHALL use updated parameters in the next execution without redeployment
4. THE ML_Pipeline SHALL validate configuration parameters before pipeline execution and fail fast if invalid
5. THE ML_Pipeline SHALL log active configuration parameters at the start of each pipeline execution
6. WHERE sensitive parameters are needed, THE ML_Pipeline SHALL retrieve them from AWS Secrets Manager

### Requirement 12: Integration with Existing API Services

**User Story:** As a backend developer, I want the ML pipeline to integrate seamlessly with existing ECS services, so that the API can serve fresh predictions

#### Acceptance Criteria

1. WHEN scoring completes, THE ML_Pipeline SHALL update risk scores in the Data_Store on EFS accessible by ECS backend tasks
2. THE ML_Pipeline SHALL maintain backward compatibility with existing DuckDB schema and table structures
3. THE ML_Pipeline SHALL notify the backend API service via SNS when new scores are available
4. THE ML_Pipeline SHALL support API-triggered pipeline execution via Lambda function integrated with existing FastAPI endpoints
5. THE ML_Pipeline SHALL use the same EFS mount point as ECS backend tasks for shared access to Data_Store and artifacts
6. THE ML_Pipeline SHALL preserve existing model artifact formats (JSON, LGBM, PKL) for compatibility with scoring code

### Requirement 13: Data Preprocessing with SageMaker Processing

**User Story:** As a data scientist, I want automated data preprocessing and feature engineering using SageMaker Processing Jobs, so that data preparation is scalable and reproducible

#### Acceptance Criteria

1. THE ML_Pipeline SHALL execute SageMaker Processing Jobs for data preprocessing before model training
2. THE Processing_Job SHALL run on ml.m5.xlarge instances with 4 vCPU and 16GB RAM for feature engineering workloads
3. THE Processing_Job SHALL read raw data from S3 and DuckDB on EFS
4. WHEN preprocessing completes, THE Processing_Job SHALL write processed features to S3 in Parquet format
5. THE Processing_Job SHALL generate data quality reports including null percentages, outlier counts, and feature distributions
6. THE Processing_Job SHALL use spot instances when available to reduce preprocessing costs
7. THE Processing_Job SHALL support custom preprocessing scripts from the bitoguard_core/features module

### Requirement 14: Hyperparameter Optimization with SageMaker Tuning

**User Story:** As a data scientist, I want automated hyperparameter tuning for models, so that I can find optimal configurations without manual experimentation

#### Acceptance Criteria

1. THE ML_Pipeline SHALL support SageMaker Hyperparameter Tuning Jobs for LightGBM and CatBoost models
2. THE Tuning_Job SHALL optimize for precision@100 metric using Bayesian optimization strategy
3. THE Tuning_Job SHALL run up to 20 training jobs with maximum 3 parallel jobs
4. THE Tuning_Job SHALL search hyperparameter ranges including learning_rate (0.01-0.3), num_leaves (20-100), and n_estimators (100-500)
5. WHEN tuning completes, THE Tuning_Job SHALL select the best model based on validation metrics
6. THE Tuning_Job SHALL save all trial results to S3 with hyperparameters and metrics for analysis
7. THE Tuning_Job SHALL use spot instances for training jobs to minimize tuning costs

### Requirement 15: Model Versioning with SageMaker Model Registry

**User Story:** As an MLOps engineer, I want centralized model versioning and approval workflows, so that only validated models are deployed to production

#### Acceptance Criteria

1. THE ML_Pipeline SHALL register trained models in SageMaker Model Registry with model package groups
2. THE Model_Registry SHALL maintain separate model package groups for lgbm, catboost, and iforest models
3. WHEN a model is registered, THE Model_Registry SHALL store model artifacts, metadata, and evaluation metrics
4. THE Model_Registry SHALL support model approval workflow with PendingApproval, Approved, and Rejected statuses
5. THE ML_Pipeline SHALL only deploy models with Approved status to inference endpoints
6. THE Model_Registry SHALL track model lineage including training job, dataset version, and hyperparameters
7. THE Model_Registry SHALL support model versioning with automatic version incrementing

### Requirement 16: Real-Time Inference with SageMaker Endpoints

**User Story:** As a backend developer, I want real-time model inference via SageMaker Endpoints, so that the API can serve predictions with low latency

#### Acceptance Criteria

1. THE ML_Pipeline SHALL deploy approved models to SageMaker real-time endpoints
2. THE Endpoint SHALL use ml.t3.medium instances with 2 vCPU and 4GB RAM for cost-effective inference
3. THE Endpoint SHALL support auto-scaling based on invocation rate with minimum 1 and maximum 3 instances
4. WHEN the endpoint receives a request, IT SHALL return risk score predictions within 200ms at p95 latency
5. THE Endpoint SHALL expose a REST API accepting JSON input with user features
6. THE Endpoint SHALL support A/B testing by routing traffic between multiple model variants
7. THE Endpoint SHALL publish invocation metrics to CloudWatch including latency, error rate, and throughput

### Requirement 17: Batch Inference with SageMaker Batch Transform

**User Story:** As a data scientist, I want batch scoring for large datasets, so that I can efficiently score all users without overloading real-time endpoints

#### Acceptance Criteria

1. THE ML_Pipeline SHALL execute SageMaker Batch Transform Jobs for scoring large user populations
2. THE Batch_Transform_Job SHALL read feature data from S3 in Parquet format
3. THE Batch_Transform_Job SHALL use ml.m5.xlarge instances with batch size of 100 records
4. WHEN batch transform completes, IT SHALL write predictions to S3 in JSON Lines format
5. THE Batch_Transform_Job SHALL process up to 10,000 users in a single job
6. THE Batch_Transform_Job SHALL use spot instances to reduce batch inference costs
7. THE Batch_Transform_Job SHALL support model monitoring by capturing input features and predictions

### Requirement 18: Local Model Training Mode

**User Story:** As a data scientist, I want to train models locally without SageMaker, so that I can iterate quickly during development and reduce cloud costs for experimentation

#### Acceptance Criteria

1. THE ML_Pipeline SHALL support local training mode using existing train.py, train_catboost.py, and anomaly.py modules
2. WHEN local training mode is selected, THE Training_Service SHALL execute training on ECS Fargate tasks with 4 vCPU and 8GB RAM
3. THE Training_Service SHALL train LightGBM, CatBoost, and IsolationForest models using the same hyperparameters as SageMaker training
4. WHEN local training completes, THE Training_Service SHALL save model artifacts in joblib format with SHA256 checksums
5. THE Training_Service SHALL generate training metadata including feature columns, encoded columns, train/valid/holdout date splits, and feature importance
6. THE Training_Service SHALL log training progress and metrics to CloudWatch Logs with structured JSON format
7. THE Training_Service SHALL terminate ECS tasks within 2 minutes of training completion

### Requirement 19: 5-Fold Cross-Validation Evaluation

**User Story:** As a data scientist, I want to evaluate models using 5-fold cross-validation, so that I can assess model performance robustness and generalization

#### Acceptance Criteria

1. THE ML_Pipeline SHALL support 5-fold cross-validation for LightGBM, CatBoost, and IsolationForest models
2. THE Training_Service SHALL split training data into 5 stratified folds preserving positive class distribution
3. FOR EACH fold, THE Training_Service SHALL train a model on 4 folds and evaluate on the held-out fold
4. THE Training_Service SHALL compute precision@100, precision@200, recall, F1-score, and AUC-ROC for each fold
5. WHEN cross-validation completes, THE Training_Service SHALL aggregate metrics across folds with mean and standard deviation
6. THE Training_Service SHALL save cross-validation results to S3 in JSON format with per-fold metrics and aggregated statistics
7. THE Training_Service SHALL generate a cross-validation report including fold-wise performance comparison and metric stability analysis

### Requirement 20: Training Mode Selection

**User Story:** As an MLOps engineer, I want to configure training mode via parameters, so that I can choose between local and SageMaker training based on workload requirements

#### Acceptance Criteria

1. THE ML_Pipeline SHALL read training_mode parameter from AWS Systems Manager Parameter Store with values "local" or "sagemaker"
2. WHEN training_mode is "local", THE Pipeline_Orchestrator SHALL execute local training on ECS Fargate tasks
3. WHEN training_mode is "sagemaker", THE Pipeline_Orchestrator SHALL execute SageMaker Training Jobs
4. THE ML_Pipeline SHALL validate training_mode parameter before pipeline execution and fail fast if invalid
5. THE ML_Pipeline SHALL log the selected training mode at pipeline start with timestamp and execution ID
6. THE ML_Pipeline SHALL support per-model training mode configuration allowing mixed local and SageMaker training
7. WHERE training_mode is not specified, THE ML_Pipeline SHALL default to "local" mode for backward compatibility

### Requirement 21: Unified Artifact Management for Local and SageMaker Training

**User Story:** As a data scientist, I want local and SageMaker training to use the same artifact storage, so that model versioning and deployment workflows are consistent

#### Acceptance Criteria

1. THE Artifact_Manager SHALL store local training artifacts in the same S3 Model_Registry as SageMaker artifacts
2. THE Artifact_Manager SHALL organize local training artifacts using the same path structure: `s3://bucket/models/{model_type}/{version}/`
3. WHEN local training completes, THE Artifact_Manager SHALL upload model files, metadata JSON, and SHA256 checksums to S3
4. THE Artifact_Manager SHALL tag local training artifacts with training_mode=local metadata for tracking
5. THE Artifact_Manager SHALL maintain the same manifest file format for local and SageMaker models
6. THE Artifact_Manager SHALL support retrieval of local and SageMaker models using the same API
7. THE Artifact_Manager SHALL apply the same lifecycle policies to local and SageMaker artifacts

### Requirement 22: Performance Comparison Between Local and SageMaker Training

**User Story:** As a data scientist, I want to compare local and SageMaker training performance, so that I can validate training mode equivalence and choose the optimal mode

#### Acceptance Criteria

1. THE ML_Pipeline SHALL produce comparable evaluation metrics for local and SageMaker training using the same test dataset
2. THE Training_Service SHALL log training duration, resource utilization, and cost estimates for both training modes
3. THE Monitoring_Service SHALL create CloudWatch dashboards comparing local vs SageMaker training metrics side-by-side
4. THE Training_Service SHALL validate that local and SageMaker models produce predictions within 5% relative difference on holdout data
5. THE Training_Service SHALL generate a training comparison report including metrics, duration, cost, and model artifact sizes
6. THE Training_Service SHALL log warnings if local and SageMaker training produce significantly different feature importance rankings
7. THE Monitoring_Service SHALL track training mode usage statistics including execution counts, success rates, and average costs

