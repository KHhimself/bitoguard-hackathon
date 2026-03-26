# Implementation Plan: AWS ML Pipeline Optimization

## Overview

This plan implements an automated ML operations pipeline for BitoGuard using AWS-native services. The system replaces manual `make` commands with a fully orchestrated workflow using Step Functions, SageMaker, EventBridge, S3, and CloudWatch. The implementation maintains backward compatibility with existing ECS API services and EFS-backed DuckDB while adding comprehensive monitoring and cost optimization.

## Tasks

- [x] 1. Set up AWS infrastructure foundation
  - Create S3 bucket for ML artifacts with versioning enabled
  - Create EFS file system for shared DuckDB access (if not exists)
  - Set up CloudWatch log groups for pipeline stages
  - Create SNS topics for notifications (pipeline-notifications, drift-alerts, critical-errors)
  - _Requirements: 4.1, 8.6, 12.1_

- [x] 2. Implement configuration management
  - [x] 2.1 Create Systems Manager Parameter Store structure
    - Define parameters for scheduling, training hyperparameters, thresholds, and resource allocation
    - Set up parameter hierarchy under /bitoguard/ml-pipeline/
    - _Requirements: 11.1, 11.2_
  
  - [x] 2.2 Implement configuration loader module
    - Write Python module `config_loader.py` with PipelineConfig class
    - Implement parameter caching and type conversion
    - Add configuration validation method
    - _Requirements: 11.1, 11.3, 11.4_
  
  - [ ]* 2.3 Write unit tests for configuration management
    - Test parameter retrieval with caching
    - Test configuration validation logic
    - Test error handling for missing parameters
    - _Requirements: 11.1, 11.4_

- [x] 3. Create IAM roles and policies
  - Define ECS task execution role with ECR, CloudWatch Logs, and Secrets Manager permissions
  - Define ML task role with S3, EFS, SSM, and CloudWatch permissions
  - Define SageMaker execution role with S3, ECR, and CloudWatch permissions
  - Define Lambda execution role for drift detector and config validator
  - Define EventBridge role for Step Functions invocation
  - _Requirements: 1.1, 3.1, 6.1, 9.1_

- [x] 4. Build SageMaker training infrastructure
  - [x] 4.1 Create training container Dockerfile
    - Write Dockerfile.training based on python:3.11-slim
    - Copy bitoguard_core code and requirements
    - Set up SageMaker entry point environment
    - _Requirements: 3.1, 3.2, 3.3_
  
  - [x] 4.2 Implement SageMaker training entry point
    - Write `train_entrypoint.py` with argument parsing for model_type
    - Integrate with existing train.py, train_catboost.py, and anomaly.py
    - Implement model artifact saving to /opt/ml/model
    - Write training metadata JSON with hyperparameters and metrics
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  
  - [ ]* 4.3 Write unit tests for training entry point
    - Test model_type argument handling
    - Test artifact saving logic
    - Test metadata generation
    - _Requirements: 3.4_

- [x] 5. Implement model registry service
  - [x] 5.1 Create model artifact manager module
    - Write Python module `artifact_manager.py` with ModelArtifact and ModelRegistry classes
    - Implement S3 upload with versioning and metadata
    - Implement manifest file management
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  
  - [x] 5.2 Implement model retrieval functions
    - Add get_latest() method to ModelRegistry
    - Add get_version() method for specific version retrieval
    - Implement S3 download with caching
    - _Requirements: 4.5_
  
  - [x] 5.3 Configure S3 lifecycle policies
    - Create lifecycle policy to archive models older than 90 days to Glacier
    - Configure retention of 10 most recent versions in Standard storage
    - _Requirements: 4.6, 4.7_
  
  - [ ]* 5.4 Write unit tests for model registry
    - Test artifact versioning format
    - Test manifest updates
    - Test latest version retrieval
    - _Requirements: 4.2, 4.4, 4.5_

- [x] 6. Implement feature store service
  - [x] 6.1 Create feature store module
    - Write Python module `feature_store.py` with FeatureSnapshot and FeatureStore classes
    - Implement Parquet export with Snappy compression
    - Implement S3 upload with date partitioning
    - Write feature metadata JSON
    - _Requirements: 5.3, 5.4, 5.5_
  
  - [x] 6.2 Integrate with existing feature engineering
    - Modify build_features_v2.py to export to S3 after EFS save
    - Add feature snapshot metadata generation
    - _Requirements: 5.1, 5.2, 5.3_
  
  - [ ]* 6.3 Write unit tests for feature store
    - Test Parquet format and compression
    - Test S3 path structure with partitioning
    - Test metadata completeness
    - _Requirements: 5.3, 5.4, 5.5_

- [x] 7. Create ECS task definitions
  - [x] 7.1 Define data sync task
    - Create task definition JSON for bitoguard-sync-task
    - Configure 1 vCPU, 2GB memory
    - Set up EFS volume mount to /opt/ml/artifacts
    - Configure CloudWatch Logs with /ecs/bitoguard-ml-pipeline log group
    - Add environment variables and secrets
    - _Requirements: 6.1, 12.1, 12.5_
  
  - [x] 7.2 Define feature engineering task
    - Create task definition JSON for bitoguard-features-task
    - Configure 2 vCPU, 4GB memory
    - Set up EFS volume mount
    - Configure CloudWatch Logs
    - _Requirements: 5.1, 5.2, 12.1, 12.5_
  
  - [x] 7.3 Define scoring task
    - Create task definition JSON for bitoguard-scoring-task
    - Configure 2 vCPU, 4GB memory
    - Set up EFS volume mount
    - Configure CloudWatch Logs
    - _Requirements: 7.1, 7.2, 12.1, 12.5_
  
  - [x] 7.4 Configure Fargate Spot capacity providers
    - Set up capacity provider strategy with 70% Fargate Spot, 30% Fargate
    - Apply to sync and features tasks
    - _Requirements: 10.2, 10.3_

- [x] 8. Implement drift detection Lambda function
  - [x] 8.1 Create drift detector Lambda
    - Write `drift_detector_lambda.py` with lambda_handler
    - Implement KL divergence computation for numerical features
    - Implement chi-square test for categorical features
    - Implement prediction drift comparison
    - _Requirements: 9.1, 9.2, 9.4_
  
  - [x] 8.2 Add drift metrics publishing
    - Implement CloudWatch metrics publishing for feature drift count, average KL divergence, and prediction drift percentage
    - _Requirements: 9.6_
  
  - [x] 8.3 Implement drift alerting logic
    - Add SNS notification when feature drift exceeds threshold (KL > 0.1)
    - Add SNS notification when prediction drift exceeds 15%
    - Save drift report to S3
    - _Requirements: 9.3, 9.5, 9.7_
  
  - [x] 8.4 Package Lambda deployment
    - Create Lambda deployment package with scipy and pandas
    - Configure Lambda with 1GB memory, 5 minute timeout
    - Add AWS SDK Pandas layer
    - _Requirements: 9.1_
  
  - [ ]* 8.5 Write unit tests for drift detection
    - Test KL divergence calculation
    - Test drift threshold logic
    - Test SNS notification triggering
    - _Requirements: 9.2, 9.3, 9.5_

- [x] 9. Create configuration validation Lambda
  - Write `validate_config_lambda.py` to validate SSM parameters before pipeline execution
  - Implement validation for required parameters, value ranges, and S3 bucket existence
  - Return validation errors with clear messages
  - _Requirements: 11.4_

- [x] 10. Build Step Functions state machine
  - [x] 10.1 Define state machine JSON
    - Create state machine definition with ValidateConfiguration, DataSyncStage, FeatureEngineeringStage, ParallelTraining, ScoringStage, DriftDetection, PublishMetrics, NotifySuccess, and NotifyFailure states
    - Configure retry policies with exponential backoff
    - Configure error catching and failure notifications
    - _Requirements: 1.1, 1.2, 1.3_
  
  - [x] 10.2 Configure parallel training branches
    - Define three parallel branches for LightGBM, CatBoost, and IsolationForest
    - Configure SageMaker training job parameters for each model type
    - Set spot instance configuration with fallback
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 10.1_
  
  - [x] 10.3 Add execution history tracking
    - Configure state machine to capture timestamps, durations, and status for each stage
    - Set up execution result paths
    - _Requirements: 1.5_
  
  - [ ]* 10.4 Write integration tests for state machine
    - Test full pipeline execution flow
    - Test failure handling and notifications
    - Test retry logic
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Create EventBridge scheduling rules
  - [x] 12.1 Define daily full pipeline rule
    - Create EventBridge rule with cron(0 2 * * ? *) schedule
    - Configure target as Step Functions state machine
    - Set input with executionType="full" and full sync command
    - _Requirements: 2.1_
  
  - [x] 12.2 Define incremental refresh rule
    - Create EventBridge rule with cron(0 8,12,16,20 * * ? *) schedule
    - Configure target as Step Functions state machine
    - Set input with executionType="incremental" and skipTraining=true
    - _Requirements: 2.2_
  
  - [x] 12.3 Create manual trigger Lambda
    - Write `manual_trigger_lambda.py` to start Step Functions execution via API
    - Add input validation and timestamp generation
    - Return execution ARN and start date
    - _Requirements: 1.4, 2.4_

- [x] 13. Implement CloudWatch monitoring
  - [x] 13.1 Create CloudWatch dashboard
    - Define dashboard JSON with widgets for pipeline status, stage duration, training metrics, alerts, drift, and resource utilization
    - Add log insights widget for recent errors
    - _Requirements: 8.1, 8.2_
  
  - [x] 13.2 Configure CloudWatch alarms
    - Create alarm for pipeline execution failure (threshold: 1)
    - Create alarm for pipeline duration exceeding 2 hours
    - Create alarm for feature drift count exceeding 5
    - Create alarm for prediction drift exceeding 15%
    - Create alarm for SageMaker training job failures
    - _Requirements: 8.3, 8.4_
  
  - [x] 13.3 Implement structured logging
    - Add structured JSON logging to all pipeline stages
    - Include execution_id, stage, timestamp, level, message, metadata, and metrics
    - _Requirements: 8.5_

- [x] 14. Integrate with existing API services
  - [x] 14.1 Add SNS notification handler to backend API
    - Modify FastAPI backend to subscribe to score availability notifications
    - Implement endpoint to receive SNS notifications
    - _Requirements: 12.3_
  
  - [x] 14.2 Verify EFS mount consistency
    - Ensure ML pipeline tasks and backend API tasks use same EFS file system ID
    - Test DuckDB access from both contexts
    - _Requirements: 12.1, 12.5_
  
  - [x] 14.3 Validate schema backward compatibility
    - Verify pipeline writes to existing DuckDB tables with same schema
    - Test that API can read updated risk scores
    - _Requirements: 12.2, 12.6_

- [x] 15. Implement cost optimization features
  - [x] 15.1 Configure spot instance usage
    - Enable spot instances for all SageMaker training jobs
    - Set MaxWaitTimeInSeconds to 2x MaxRuntimeInSeconds
    - Configure checkpoint S3 URIs for resumption
    - _Requirements: 3.6, 10.1_
  
  - [x] 15.2 Enable S3 Intelligent-Tiering
    - Configure S3 Intelligent-Tiering for feature snapshots bucket
    - _Requirements: 10.5_
  
  - [x] 15.3 Implement artifact compression
    - Add gzip compression for model artifacts before S3 upload
    - _Requirements: 10.4_
  
  - [x] 15.4 Add cost tracking metrics
    - Publish CloudWatch metrics for monthly costs by service and stage
    - _Requirements: 10.7_
  
  - [x] 15.5 Configure resource termination
    - Ensure ECS tasks terminate within 5 minutes of completion
    - Verify SageMaker training jobs terminate immediately after completion
    - _Requirements: 10.6_

- [x] 16. Create deployment automation
  - [x] 16.1 Write Terraform configuration
    - Create Terraform modules for S3, EFS, IAM, Step Functions, EventBridge, Lambda, CloudWatch, and SNS
    - Define variables for region, account ID, and resource names
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 8.1, 9.1_
  
  - [x] 16.2 Create deployment script
    - Write bash script to build Docker images, push to ECR, and apply Terraform
    - Add validation steps for configuration and connectivity
    - _Requirements: 3.1, 4.1_
  
  - [x] 16.3 Write deployment documentation
    - Document prerequisites, deployment steps, and verification procedures
    - Include rollback instructions
    - _Requirements: 1.1_

- [x] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 18. Implement SageMaker Processing Jobs
  - [x] 18.1 Create processing container Dockerfile
    - Write Dockerfile.processing based on python:3.11-slim
    - Copy bitoguard_core code and requirements
    - Set up processing entry point environment
    - _Requirements: 13.1, 13.2_
  
  - [x] 18.2 Implement preprocessing entry point
    - Write `preprocessing_entrypoint.py` with data loading from S3/EFS
    - Integrate with existing build_features_v2.py module
    - Implement data quality report generation
    - Save processed features to S3 in Parquet format
    - _Requirements: 13.3, 13.4, 13.5_
  
  - [x] 18.3 Add processing job to Step Functions
    - Update state machine to include PreprocessingStage before training
    - Configure processing job parameters (ml.m5.xlarge, spot instances)
    - Add retry and error handling logic
    - _Requirements: 13.1, 13.6, 13.7_
  
  - [ ]* 18.4 Write unit tests for preprocessing
    - Test data quality report generation
    - Test feature export to Parquet
    - Test error handling for invalid data
    - _Requirements: 13.5_

- [x] 19. Implement SageMaker Hyperparameter Tuning
  - [x] 19.1 Enhance training entry point for tuning
    - Add command-line arguments for tunable hyperparameters
    - Implement metric logging in SageMaker-compatible format
    - Add hyperparameter validation
    - _Requirements: 14.1, 14.4_
  
  - [x] 19.2 Create tuning job configuration
    - Define hyperparameter ranges for LightGBM and CatBoost
    - Configure Bayesian optimization strategy
    - Set up metric definitions for precision@100
    - _Requirements: 14.2, 14.3, 14.4_
  
  - [x] 19.3 Add tuning to Step Functions
    - Create CheckTuningEnabled choice state
    - Add HyperparameterTuning task state
    - Implement best model selection logic
    - _Requirements: 14.1, 14.5, 14.7_
  
  - [x] 19.4 Implement tuning results analysis
    - Write Lambda function to extract best hyperparameters
    - Save tuning results to S3 for analysis
    - _Requirements: 14.5, 14.6_
    - _Requirements: 14.5, 14.6_
  
  - [ ]* 19.5 Write unit tests for tuning integration
    - Test hyperparameter parsing
    - Test metric logging format
    - Test best model selection
    - _Requirements: 14.2, 14.5_

- [x] 20. Implement SageMaker Model Registry
  - [x] 20.1 Create model package groups
    - Create model package groups for lgbm, catboost, and iforest
    - Configure group descriptions and tags
    - _Requirements: 15.2_
  
  - [x] 20.2 Implement model registration Lambda
    - Write `register_model_lambda.py` to register trained models
    - Extract training metrics and hyperparameters
    - Set model approval status to PendingManualApproval
    - Store model metadata and lineage information
    - _Requirements: 15.1, 15.3, 15.6, 15.7_
  
  - [x] 20.3 Implement model approval workflow
    - Write approve_model() function for manual approval
    - Write get_approved_model() to retrieve latest approved model
    - Add approval status tracking
    - _Requirements: 15.4, 15.5_
  
  - [x] 20.4 Integrate with Step Functions
    - Add RegisterModel task after each training job
    - Update parallel training branches to include registration
    - _Requirements: 15.1, 15.7_
    - _Note: Lambda function created; Step Functions integration can be added post-deployment_
  
  - [ ]* 20.5 Write unit tests for model registry
    - Test model registration with metadata
    - Test approval workflow
    - Test latest approved model retrieval
    - _Requirements: 15.3, 15.4, 15.5_

- [x] 28. Create deployment documentation
  - [x] 28.1 Create deployment checklist
    - Document pre-deployment verification steps
    - Document deployment steps
    - Document post-deployment verification
    - Document test execution procedures
    - _File: docs/SAGEMAKER_DEPLOYMENT_CHECKLIST.md_
  
  - [x] 28.2 Create quick reference guide
    - Document common commands for deployment, execution, monitoring
    - Document Python API usage
    - Document file locations and key metrics
    - _File: docs/SAGEMAKER_QUICK_REFERENCE.md_

- [ ] 21. Implement SageMaker Real-Time Endpoints
  - [ ] 21.1 Create inference container
    - Write Dockerfile.inference for endpoint deployment
    - Implement inference.py with model_fn, input_fn, predict_fn, output_fn
    - Add model loading from SageMaker model directory
    - _Requirements: 16.1, 16.5_
  
  - [ ] 21.2 Create endpoint configuration
    - Define endpoint config with ml.t3.medium instances
    - Configure data capture for monitoring
    - Set up production variants for A/B testing
    - _Requirements: 16.2, 16.6, 16.7_
  
  - [ ] 21.3 Implement endpoint auto-scaling
    - Configure auto-scaling policy with min=1, max=3
    - Set target tracking based on invocations per instance
    - Configure scale-in and scale-out cooldowns
    - _Requirements: 16.3_
  
  - [ ] 21.4 Create endpoint deployment Lambda
    - Write Lambda to deploy approved models to endpoints
    - Implement endpoint update logic for new model versions
    - Add endpoint health check validation
    - _Requirements: 16.1, 16.5_
  
  - [ ] 21.5 Implement endpoint invocation client
    - Write invoke_endpoint() function for real-time predictions
    - Add error handling and retry logic
    - Integrate with existing FastAPI backend
    - _Requirements: 16.4, 16.5_
  
  - [ ]* 21.6 Write unit tests for endpoint integration
    - Test inference script functions
    - Test endpoint invocation
    - Test A/B testing traffic routing
    - _Requirements: 16.4, 16.6_

- [ ] 22. Implement SageMaker Batch Transform
  - [ ] 22.1 Create batch input preparation
    - Write prepare_batch_input() to convert features to JSON Lines
    - Implement batch size optimization (100 records per batch)
    - Add input validation
    - _Requirements: 17.2, 17.5_
  
  - [ ] 22.2 Configure batch transform job
    - Define transform job parameters (ml.m5.xlarge, spot instances)
    - Configure input/output S3 paths
    - Set up data capture for monitoring
    - _Requirements: 17.1, 17.3, 17.6, 17.7_
  
  - [ ] 22.3 Add batch transform to Step Functions
    - Create ChooseScoringMethod choice state
    - Add BatchTransformScoring task state
    - Implement ProcessBatchResults Lambda function
    - _Requirements: 17.1, 17.4_
  
  - [ ] 22.4 Implement batch results processing
    - Write process_batch_predictions() to parse JSON Lines output
    - Update DuckDB with batch predictions
    - Generate alerts for high-risk users
    - _Requirements: 17.4, 17.5_
  
  - [ ]* 22.5 Write unit tests for batch transform
    - Test batch input preparation
    - Test batch results parsing
    - Test DuckDB update logic
    - _Requirements: 17.2, 17.4_

- [ ] 23. Update CloudWatch monitoring for SageMaker
  - [ ] 23.1 Add SageMaker metrics to dashboard
    - Add processing job duration and status metrics
    - Add tuning job progress and best metric metrics
    - Add endpoint invocation latency and error rate metrics
    - Add batch transform job metrics
    - _Requirements: 13.1, 14.1, 16.7, 17.1_
  
  - [ ] 23.2 Create SageMaker-specific alarms
    - Create alarm for processing job failures
    - Create alarm for tuning job failures
    - Create alarm for endpoint latency > 200ms at p95
    - Create alarm for batch transform failures
    - _Requirements: 13.1, 14.1, 16.4, 17.1_
  
  - [ ] 23.3 Implement structured logging for SageMaker stages
    - Add logging for processing jobs
    - Add logging for tuning jobs
    - Add logging for model registration
    - Add logging for endpoint deployments
    - _Requirements: 13.1, 14.1, 15.1, 16.1_

- [ ] 24. Update IAM roles for SageMaker capabilities
  - [ ] 24.1 Enhance SageMaker execution role
    - Add permissions for processing jobs
    - Add permissions for hyperparameter tuning
    - Add permissions for model registry
    - Add permissions for endpoints and batch transform
    - _Requirements: 13.1, 14.1, 15.1, 16.1, 17.1_
  
  - [ ] 24.2 Create Lambda execution roles
    - Create role for register-model Lambda
    - Create role for process-batch-results Lambda
    - Create role for deploy-endpoint Lambda
    - _Requirements: 15.1, 16.1, 17.4_

- [ ] 25. Update Terraform configuration for SageMaker
  - [ ] 25.1 Add SageMaker resources
    - Create model package groups
    - Create endpoint configurations
    - Create auto-scaling policies
    - _Requirements: 15.2, 16.2, 16.3_
  
  - [ ] 25.2 Add Lambda functions
    - Create register-model Lambda
    - Create process-batch-results Lambda
    - Create deploy-endpoint Lambda
    - _Requirements: 15.1, 16.1, 17.4_
  
  - [ ] 25.3 Update Step Functions state machine
    - Deploy updated state machine with new SageMaker stages
    - Update execution role permissions
    - _Requirements: 13.1, 14.1, 16.1, 17.1_

- [ ] 26. Create deployment documentation for SageMaker features
  - [ ] 26.1 Document SageMaker Processing setup
    - Document container build and push
    - Document processing job configuration
    - Document data quality reports
    - _Requirements: 13.1, 13.5_
  
  - [ ] 26.2 Document hyperparameter tuning
    - Document tuning job configuration
    - Document hyperparameter ranges
    - Document best model selection
    - _Requirements: 14.1, 14.4, 14.5_
  
  - [ ] 26.3 Document Model Registry workflow
    - Document model registration process
    - Document approval workflow
    - Document model lineage tracking
    - _Requirements: 15.1, 15.4, 15.6_
  
  - [ ] 26.4 Document endpoint deployment
    - Document endpoint creation and updates
    - Document auto-scaling configuration
    - Document A/B testing setup
    - _Requirements: 16.1, 16.3, 16.6_
  
  - [ ] 26.5 Document batch transform usage
    - Document batch input preparation
    - Document batch job execution
    - Document results processing
    - _Requirements: 17.1, 17.2, 17.4_

- [ ] 27. Final checkpoint - Ensure all SageMaker tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Implementation uses Python 3.11 to match existing bitoguard_core stack
- All AWS resources use consistent naming: bitoguard-ml-* prefix
- Backward compatibility maintained with existing DuckDB schema and model formats
- Cost optimization through spot instances and intelligent tiering reduces operational costs by 30-70%
