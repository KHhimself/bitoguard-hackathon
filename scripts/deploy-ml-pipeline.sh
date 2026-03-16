#!/bin/bash
set -e

# BitoGuard ML Pipeline Deployment Script
# Builds Docker images, packages Lambda functions, and deploys infrastructure

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAMBDA_DIR="$PROJECT_ROOT/infra/aws/lambda"
TERRAFORM_DIR="$PROJECT_ROOT/infra/aws/terraform"

echo "=========================================="
echo "BitoGuard ML Pipeline Deployment"
echo "=========================================="

# Check prerequisites
echo "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "Error: docker is required but not installed."; exit 1; }
command -v terraform >/dev/null 2>&1 || { echo "Error: terraform is required but not installed."; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "Error: aws CLI is required but not installed."; exit 1; }

# Get AWS account ID and region
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_REGION:-us-east-1}
ECR_REGISTRY="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

echo "AWS Account ID: $AWS_ACCOUNT_ID"
echo "AWS Region: $AWS_REGION"

# Step 1: Build and push training Docker image
echo ""
echo "Step 1: Building training Docker image..."
cd "$PROJECT_ROOT/bitoguard_core"

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY

# Build training image
docker build -f Dockerfile.training -t bitoguard-training:latest .
docker tag bitoguard-training:latest $ECR_REGISTRY/bitoguard-backend:training
docker push $ECR_REGISTRY/bitoguard-backend:training

echo "✓ Training image pushed to ECR"

# Step 2: Package Lambda functions
echo ""
echo "Step 2: Packaging Lambda functions..."

package_lambda() {
    local lambda_name=$1
    local lambda_path="$LAMBDA_DIR/$lambda_name"
    local zip_file="$LAMBDA_DIR/${lambda_name}.zip"
    
    echo "  Packaging $lambda_name..."
    
    # Create temporary directory
    local temp_dir=$(mktemp -d)
    
    # Copy Lambda code
    cp "$lambda_path/lambda_function.py" "$temp_dir/"
    
    # Install dependencies if requirements.txt exists
    if [ -f "$lambda_path/requirements.txt" ]; then
        pip install -r "$lambda_path/requirements.txt" -t "$temp_dir/" --quiet
    fi
    
    # Create zip file
    cd "$temp_dir"
    zip -r "$zip_file" . >/dev/null
    cd - >/dev/null
    
    # Cleanup
    rm -rf "$temp_dir"
    
    echo "  ✓ $lambda_name packaged"
}

package_lambda "drift_detector"
package_lambda "config_validator"
package_lambda "manual_trigger"

echo "✓ All Lambda functions packaged"

# Step 3: Initialize Terraform
echo ""
echo "Step 3: Initializing Terraform..."
cd "$TERRAFORM_DIR"

if [ ! -f "terraform.tfvars" ]; then
    echo "Error: terraform.tfvars not found. Please create it from terraform.tfvars.example"
    exit 1
fi

terraform init

echo "✓ Terraform initialized"

# Step 4: Plan Terraform changes
echo ""
echo "Step 4: Planning Terraform changes..."
terraform plan -out=tfplan

# Step 5: Apply Terraform
echo ""
echo "Step 5: Applying Terraform configuration..."
read -p "Do you want to apply these changes? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Deployment cancelled"
    exit 0
fi

terraform apply tfplan

echo "✓ Infrastructure deployed"

# Step 6: Get outputs
echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "ML Pipeline Resources:"
terraform output -json | jq -r '
  "State Machine ARN: " + .ml_pipeline_state_machine_arn.value,
  "Manual Trigger URL: " + .manual_trigger_function_url.value,
  "Dashboard: " + .ml_pipeline_dashboard_name.value,
  "Artifacts Bucket: " + .ml_artifacts_bucket.value
'

echo ""
echo "Next Steps:"
echo "1. Configure SSM parameters in AWS Systems Manager"
echo "2. Test manual trigger: curl -X POST <manual_trigger_url> -d '{\"execution_type\":\"full\"}'"
echo "3. Monitor pipeline execution in Step Functions console"
echo "4. View metrics in CloudWatch dashboard"

# Cleanup
rm -f tfplan
