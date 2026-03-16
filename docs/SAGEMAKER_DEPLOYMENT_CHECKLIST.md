# SageMaker Features Deployment Checklist

## Pre-Deployment Verification

### 1. AWS Credentials
```bash
# Verify AWS credentials are configured
aws sts get-caller-identity

# Expected output:
# {
#     "UserId": "...",
#     "Account": "123456789012",
#     "Arn": "arn:aws:iam::123456789012:user/..."
# }
```

### 2. Required Tools
```bash
# Check AWS CLI
aws --version
# Required: AWS CLI v2.x

# Check Terraform
terraform version
# Required: Terraform v1.0+

# Check Docker
docker --version
docker ps
# Docker must be running

# Check jq (optional but recommended)
jq --version
```

### 3. Existing Infrastructure
```bash
# Verify base infrastructure exists
cd infra/aws/terraform

# Check if Terraform is initialized
terraform init

# Verify existing resources
terraform state list | grep -E "(ecr_repository|ecs_cluster|s3_bucket)"

# Expected resources:
# - aws_ecr_repository.backend
# - aws_ecs_cluster.main
# - aws_s3_bucket.artifacts
# - aws_efs_file_system (if using EFS)
```

### 4. ECR Repositories
```bash
# Verify ECR repositories exist
aws ecr describe-repositories --repository-names bitoguard-backend bitoguard-processing bitoguard-training

# If repositories don't exist, create them:
aws ecr create-repository --repository-name bitoguard-processing
aws ecr create-repository --repository-name bitoguard-training
```

## Deployment Steps

### Step 1: Run Deployment Script
```bash
# From project root
./scripts/deploy-sagemaker-features.sh
```

The script will:
1. ✅ Check prerequisites (AWS CLI, Terraform, Docker)
2. ✅ Build Docker images (processing and training)
3. ✅ Push images to ECR
4. ✅ Package Lambda functions
5. ✅ Deploy Terraform infrastructure
6. ✅ Verify deployment

### Step 2: Monitor Deployment
```bash
# Watch Terraform apply
# Review the plan carefully before confirming with "yes"

# Expected new resources:
# - 2 Lambda functions (tuning_analyzer, model_registry)
# - 3 Model package groups (lgbm, catboost, iforest)
# - 2 IAM roles (Lambda execution roles)
# - Updated Step Functions state machine
# - SSM parameters for tuning configuration
```

## Post-Deployment Verification

### 1. Verify Step Functions
```bash
# List state machines
aws stepfunctions list-state-machines --query "stateMachines[?contains(name, 'bitoguard')].{Name:name,Arn:stateMachineArn}" --output table

# Get state machine ARN
STATE_MACHINE_ARN=$(aws stepfunctions list-state-machines --query "stateMachines[?contains(name, 'bitoguard-ml-pipeline')].stateMachineArn" --output text)

echo "State Machine ARN: $STATE_MACHINE_ARN"
```

### 2. Verify Model Package Groups
```bash
# List model package groups
aws sagemaker list-model-package-groups --query "ModelPackageGroupSummaryList[?contains(ModelPackageGroupName, 'bitoguard')].{Name:ModelPackageGroupName,Created:CreationTime}" --output table

# Expected groups:
# - bitoguard-ml-lgbm-models
# - bitoguard-ml-catboost-models
# - bitoguard-ml-iforest-models
```

### 3. Verify Lambda Functions
```bash
# List Lambda functions
aws lambda list-functions --query "Functions[?contains(FunctionName, 'bitoguard-ml')].{Name:FunctionName,Runtime:Runtime,Memory:MemorySize}" --output table

# Expected functions:
# - bitoguard-ml-tuning-analyzer
# - bitoguard-ml-model-registry
```

### 4. Verify ECR Images
```bash
# Check processing image
aws ecr describe-images --repository-name bitoguard-processing --query "imageDetails[0].{Tags:imageTags,Size:imageSizeInBytes,Pushed:imagePushedAt}" --output table

# Check training image
aws ecr describe-images --repository-name bitoguard-training --query "imageDetails[0].{Tags:imageTags,Size:imageSizeInBytes,Pushed:imagePushedAt}" --output table
```

### 5. Verify SSM Parameters
```bash
# List tuning parameters
aws ssm get-parameters-by-path --path /bitoguard/ml-pipeline/tuning --recursive --query "Parameters[].{Name:Name,Value:Value}" --output table
```

## Test Execution

### Test 1: Preprocessing Only (Quick Test)
```bash
# Start execution with skip_training=true
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --name "test-preprocessing-$(date +%Y%m%d-%H%M%S)" \
  --input '{"skip_training":true}'

# Get execution ARN from output
EXECUTION_ARN="<execution-arn-from-output>"

# Monitor execution
aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN --query "{Status:status,StartDate:startDate,StopDate:stopDate}" --output table

# Watch logs
aws logs tail /aws/sagemaker/ProcessingJobs --follow
```

### Test 2: Full Pipeline Without Tuning
```bash
# Start full pipeline execution
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --name "test-full-pipeline-$(date +%Y%m%d-%H%M%S)" \
  --input '{
    "skip_training": false,
    "enable_tuning": false,
    "baseline_snapshot_id": "20260301T120000Z",
    "current_snapshot_id": "20260315T120000Z"
  }'

# Monitor execution (takes ~30-60 minutes)
watch -n 30 "aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN --query status --output text"
```

### Test 3: Hyperparameter Tuning (Optional)
```bash
# Enable tuning via SSM parameter
aws ssm put-parameter \
  --name /bitoguard/ml-pipeline/tuning/enabled \
  --value "true" \
  --type String \
  --overwrite

# Start execution with tuning
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --name "test-tuning-$(date +%Y%m%d-%H%M%S)" \
  --input '{
    "skip_training": false,
    "enable_tuning": true
  }'

# Monitor tuning jobs (takes 2-4 hours)
aws sagemaker list-hyper-parameter-tuning-jobs --query "HyperParameterTuningJobSummaries[?contains(HyperParameterTuningJobName, 'bitoguard')].{Name:HyperParameterTuningJobName,Status:HyperParameterTuningJobStatus,BestMetric:BestTrainingJob.FinalHyperParameterTuningJobObjectiveMetric.Value}" --output table
```

## Verification Checklist

- [ ] AWS credentials configured and verified
- [ ] All required tools installed (AWS CLI, Terraform, Docker, jq)
- [ ] Base infrastructure exists (ECR, ECS, S3, EFS)
- [ ] ECR repositories created
- [ ] Deployment script executed successfully
- [ ] Step Functions state machine updated
- [ ] Model package groups created (3 groups)
- [ ] Lambda functions deployed (2 functions)
- [ ] ECR images pushed (processing and training)
- [ ] SSM parameters configured
- [ ] Test execution completed successfully
- [ ] CloudWatch logs accessible
- [ ] Model registry accessible

## Troubleshooting

### Issue: Docker build fails
```bash
# Check Docker is running
docker ps

# Check disk space
df -h

# Clean up old images
docker system prune -a
```

### Issue: ECR push fails
```bash
# Re-authenticate to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com

# Check repository exists
aws ecr describe-repositories --repository-names bitoguard-processing
```

### Issue: Terraform apply fails
```bash
# Check Terraform state
cd infra/aws/terraform
terraform state list

# Refresh state
terraform refresh

# Re-run plan
terraform plan
```

### Issue: Processing job fails
```bash
# Check logs
aws logs tail /aws/sagemaker/ProcessingJobs/bitoguard-preprocessing-* --follow

# Check EFS mount
aws efs describe-file-systems --query "FileSystems[?Name=='bitoguard-efs'].{ID:FileSystemId,State:LifeCycleState}" --output table

# Check DuckDB file exists
# (requires ECS task or EC2 instance with EFS mounted)
```

### Issue: Model registration fails
```bash
# Check Lambda logs
aws logs tail /aws/lambda/bitoguard-ml-model-registry --follow

# Check model artifacts in S3
aws s3 ls s3://bitoguard-ml-artifacts/models/ --recursive

# Verify IAM permissions
aws iam get-role --role-name bitoguard-ml-model-registry-role
```

## Rollback Procedure

If deployment fails or issues arise:

```bash
# 1. Destroy new resources
cd infra/aws/terraform
terraform destroy -target=aws_lambda_function.tuning_analyzer
terraform destroy -target=aws_lambda_function.model_registry
terraform destroy -target=aws_sagemaker_model_package_group.lgbm
terraform destroy -target=aws_sagemaker_model_package_group.catboost
terraform destroy -target=aws_sagemaker_model_package_group.iforest

# 2. Revert Step Functions state machine
# (Terraform will revert to previous version)

# 3. Remove ECR images (optional)
aws ecr batch-delete-image --repository-name bitoguard-processing --image-ids imageTag=latest
aws ecr batch-delete-image --repository-name bitoguard-training --image-ids imageTag=latest
```

## Next Steps After Successful Deployment

1. **Schedule Regular Executions**
   - Daily full pipeline: Already configured via EventBridge
   - Incremental refresh: Already configured (4x daily)

2. **Set Up Monitoring**
   - Configure CloudWatch alarms for job failures
   - Set up SNS notifications for critical errors
   - Create CloudWatch dashboard for ML metrics

3. **Model Approval Workflow**
   - Review pending model approvals regularly
   - Set up automated approval based on metrics (optional)
   - Document approval criteria

4. **Cost Optimization**
   - Monitor SageMaker costs in Cost Explorer
   - Adjust tuning frequency based on data drift
   - Review spot instance usage and savings

5. **Performance Tuning**
   - Analyze initial tuning results
   - Adjust hyperparameter ranges if needed
   - Optimize processing job instance types

## Support Resources

- **Documentation**: `docs/SAGEMAKER_FEATURES_IMPLEMENTATION.md`
- **Implementation Summary**: `docs/SAGEMAKER_IMPLEMENTATION_SUMMARY.md`
- **Architecture**: `infra/aws/ARCHITECTURE.md`
- **AWS SageMaker Docs**: https://docs.aws.amazon.com/sagemaker/

## Contact

For issues or questions:
1. Check CloudWatch Logs for error details
2. Review Terraform state for resource status
3. Consult AWS SageMaker documentation
4. Review implementation documentation in `docs/`
