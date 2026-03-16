#!/bin/bash

# BitoGuard - Direct SageMaker Training (No Infrastructure)
# For highly restricted AWS environments

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

AWS_REGION="${AWS_REGION:-us-west-2}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}BitoGuard - Direct SageMaker Training${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check SageMaker permissions
echo "Checking SageMaker permissions..."
if ! aws sagemaker list-training-jobs --max-results 1 &> /dev/null; then
    echo -e "${RED}ERROR: No SageMaker permissions${NC}"
    echo "Your role needs: sagemaker:CreateTrainingJob, sagemaker:DescribeTrainingJob"
    exit 1
fi
echo -e "${GREEN}✓ SageMaker access confirmed${NC}"

# Check S3 permissions
echo "Checking S3 permissions..."
BUCKET_NAME="bitoguard-ml-${ACCOUNT_ID}"
if aws s3 ls s3://${BUCKET_NAME} &> /dev/null 2>&1; then
    echo -e "${GREEN}✓ S3 bucket exists: ${BUCKET_NAME}${NC}"
elif aws s3 mb s3://${BUCKET_NAME} &> /dev/null 2>&1; then
    echo -e "${GREEN}✓ Created S3 bucket: ${BUCKET_NAME}${NC}"
else
    echo -e "${YELLOW}⚠ Cannot create S3 bucket, will try to use existing one${NC}"
fi

# Use the SageMaker Immersion Day execution role
echo "Checking for SageMaker execution role..."
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/sagemaker-immersion-day-SageMakerExecutionRole-xSqhC3Ls9p0E"

# Verify the role exists
if aws iam get-role --role-name sagemaker-immersion-day-SageMakerExecutionRole-xSqhC3Ls9p0E &> /dev/null; then
    echo -e "${GREEN}✓ Using role: ${ROLE_ARN}${NC}"
else
    echo -e "${YELLOW}⚠ Workshop role not found, searching for alternatives...${NC}"
    
    # Try to find any SageMaker execution role
    ROLE_ARN=$(aws iam list-roles --query 'Roles[?contains(RoleName, `SageMaker`) && contains(RoleName, `Execution`)].Arn | [0]' --output text 2>/dev/null || echo "")
    
    if [ -z "$ROLE_ARN" ] || [ "$ROLE_ARN" = "None" ]; then
        echo -e "${RED}ERROR: No SageMaker execution role found${NC}"
        echo "Please provide a role ARN:"
        read -p "Enter SageMaker role ARN: " ROLE_ARN
        
        if [ -z "$ROLE_ARN" ]; then
            exit 1
        fi
    else
        echo -e "${GREEN}✓ Found role: ${ROLE_ARN}${NC}"
    fi
fi
echo ""

# Training configuration
TRAINING_JOB_NAME="bitoguard-5fold-$(date +%Y%m%d-%H%M%S)"

echo -e "${BLUE}Training Configuration:${NC}"
echo "  Job Name: ${TRAINING_JOB_NAME}"
echo "  Instance: ml.c5.9xlarge (36 vCPUs)"
echo "  Container: XGBoost (built-in)"
echo "  Output: s3://${BUCKET_NAME}/models/"
echo ""

# Create training job
echo -e "${YELLOW}Launching SageMaker training job...${NC}"

cat > /tmp/training-job.json <<EOF
{
  "TrainingJobName": "${TRAINING_JOB_NAME}",
  "RoleArn": "${ROLE_ARN}",
  "AlgorithmSpecification": {
    "TrainingImage": "246618743249.dkr.ecr.${AWS_REGION}.amazonaws.com/sagemaker-xgboost:1.7-1",
    "TrainingInputMode": "File"
  },
  "ResourceConfig": {
    "InstanceType": "ml.c5.9xlarge",
    "InstanceCount": 1,
    "VolumeSizeInGB": 50
  },
  "StoppingCondition": {
    "MaxRuntimeInSeconds": 3600
  },
  "OutputDataConfig": {
    "S3OutputPath": "s3://${BUCKET_NAME}/models/"
  },
  "HyperParameters": {
    "objective": "binary:logistic",
    "num_round": "100",
    "max_depth": "6",
    "eta": "0.3"
  }
}
EOF

if aws sagemaker create-training-job --cli-input-json file:///tmp/training-job.json; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ Training Job Started Successfully${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Job Name: ${TRAINING_JOB_NAME}"
    echo ""
    echo "Monitor progress:"
    echo "  aws sagemaker describe-training-job --training-job-name ${TRAINING_JOB_NAME}"
    echo ""
    echo "Watch logs:"
    echo "  aws logs tail /aws/sagemaker/TrainingJobs --follow --filter-pattern ${TRAINING_JOB_NAME}"
    echo ""
    echo "AWS Console:"
    echo "  https://console.aws.amazon.com/sagemaker/home?region=${AWS_REGION}#/jobs/${TRAINING_JOB_NAME}"
    echo ""
    
    # Monitor training job
    echo -e "${YELLOW}Monitoring training job (press Ctrl+C to stop monitoring)...${NC}"
    echo ""
    
    while true; do
        STATUS=$(aws sagemaker describe-training-job \
            --training-job-name ${TRAINING_JOB_NAME} \
            --query 'TrainingJobStatus' \
            --output text 2>/dev/null || echo "UNKNOWN")
        
        echo "[$(date +%H:%M:%S)] Status: ${STATUS}"
        
        if [ "$STATUS" = "Completed" ]; then
            echo ""
            echo -e "${GREEN}✓ Training completed successfully!${NC}"
            
            # Get metrics
            aws sagemaker describe-training-job \
                --training-job-name ${TRAINING_JOB_NAME} \
                --query 'FinalMetricDataList' \
                --output table
            
            break
        elif [ "$STATUS" = "Failed" ] || [ "$STATUS" = "Stopped" ]; then
            echo ""
            echo -e "${RED}✗ Training job ${STATUS}${NC}"
            
            aws sagemaker describe-training-job \
                --training-job-name ${TRAINING_JOB_NAME} \
                --query 'FailureReason' \
                --output text
            
            exit 1
        fi
        
        sleep 30
    done
else
    echo -e "${RED}Failed to create training job${NC}"
    echo "Check your permissions and try again"
    exit 1
fi
