#!/bin/bash
set -e

# BitoGuard Full AWS + SageMaker Deployment Script
# Deploys complete infrastructure, backend API, frontend, and ML pipeline with SageMaker

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TERRAFORM_DIR="$PROJECT_ROOT/infra/aws/terraform"
LAMBDA_DIR="$PROJECT_ROOT/infra/aws/lambda"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo "=========================================="
echo "BitoGuard Full AWS + SageMaker Deployment"
echo "=========================================="
echo ""

# Check prerequisites
log_info "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { log_error "docker is required but not installed."; exit 1; }
command -v terraform >/dev/null 2>&1 || { log_error "terraform is required but not installed."; exit 1; }
command -v aws >/dev/null 2>&1 || { log_error "aws CLI is required but not installed."; exit 1; }
command -v jq >/dev/null 2>&1 || { log_error "jq is required but not installed."; exit 1; }

# Verify AWS credentials
aws sts get-caller-identity >/dev/null 2>&1 || { log_error "AWS credentials not configured."; exit 1; }

# Get AWS account details
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_REGION:-us-east-1}
ECR_REGISTRY="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

log_info "AWS Account ID: $AWS_ACCOUNT_ID"
log_info "AWS Region: $AWS_REGION"
echo ""

# Check if terraform.tfvars exists
if [ ! -f "$TERRAFORM_DIR/terraform.tfvars" ]; then
    log_error "terraform.tfvars not found!"
    log_info "Creating from example..."
    cp "$TERRAFORM_DIR/terraform.tfvars.example" "$TERRAFORM_DIR/terraform.tfvars"
    log_warn "Please edit $TERRAFORM_DIR/terraform.tfvars with your settings"
    exit 1
fi

# ==========================================
# STEP 1: Create ECR Repositories
# ==========================================
echo ""
log_info "STEP 1: Creating ECR repositories..."

create_ecr_repo() {
    local repo_name=$1
    if aws ecr describe-repositories --repository-names "$repo_name" --region $AWS_REGION >/dev/null 2>&1; then
        log_info "  ✓ Repository $repo_name already exists"
    else
        aws ecr create-repository --repository-name "$repo_name" --region $AWS_REGION >/dev/null
        log_info "  ✓ Created repository $repo_name"
    fi
}

create_ecr_repo "bitoguard-backend"
create_ecr_repo "bitoguard-frontend"

# Login to ECR
log_info "Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY

# ==========================================
# STEP 2: Build and Push Docker Images
# ==========================================
echo ""
log_info "STEP 2: Building and pushing Docker images..."

# Build backend API image
log_info "Building backend API image..."
cd "$PROJECT_ROOT/bitoguard_core"
docker build -f Dockerfile -t bitoguard-backend:latest .
docker tag bitoguard-backend:latest $ECR_REGISTRY/bitoguard-backend:latest
docker push $ECR_REGISTRY/bitoguard-backend:latest
log_info "  ✓ Backend API image pushed"

# Build training image
log_info "Building training image..."
docker build -f Dockerfile.training -t bitoguard-training:latest .
docker tag bitoguard-training:latest $ECR_REGISTRY/bitoguard-backend:training
docker push $ECR_REGISTRY/bitoguard-backend:training
log_info "  ✓ Training image pushed"

# Build processing image
log_info "Building processing image..."
docker build -f Dockerfile.processing -t bitoguard-processing:latest .
docker tag bitoguard-processing:latest $ECR_REGISTRY/bitoguard-backend:processing
docker push $ECR_REGISTRY/bitoguard-backend:processing
log_info "  ✓ Processing image pushed"

# Build frontend image
log_info "Building frontend image..."
cd "$PROJECT_ROOT/bitoguard_frontend"
docker build -t bitoguard-frontend:latest .
docker tag bitoguard-frontend:latest $ECR_REGISTRY/bitoguard-frontend:latest
docker push $ECR_REGISTRY/bitoguard-frontend:latest
log_info "  ✓ Frontend image pushed"

# ==========================================
# STEP 3: Package Lambda Functions
# ==========================================
echo ""
log_info "STEP 3: Packaging Lambda functions..."

package_lambda() {
    local lambda_name=$1
    local lambda_path="$LAMBDA_DIR/$lambda_name"
    local zip_file="$LAMBDA_DIR/${lambda_name}.zip"
    
    log_info "  Packaging $lambda_name..."
    
    # Create temporary directory
    local temp_dir=$(mktemp -d)
    
    # Copy Lambda code
    cp "$lambda_path/lambda_function.py" "$temp_dir/"
    
    # Install dependencies if requirements.txt exists
    if [ -f "$lambda_path/requirements.txt" ]; then
        pip3 install -r "$lambda_path/requirements.txt" -t "$temp_dir/" --quiet --upgrade
    fi
    
    # Create zip file
    cd "$temp_dir"
    zip -r "$zip_file" . >/dev/null
    cd - >/dev/null
    
    # Cleanup
    rm -rf "$temp_dir"
    
    log_info "  ✓ $lambda_name packaged"
}

package_lambda "drift_detector"
package_lambda "config_validator"
package_lambda "manual_trigger"
package_lambda "model_registry"
package_lambda "tuning_analyzer"

# ==========================================
# STEP 4: Deploy Infrastructure with Terraform
# ==========================================
echo ""
log_info "STEP 4: Deploying infrastructure with Terraform..."
cd "$TERRAFORM_DIR"

log_info "Initializing Terraform..."
terraform init

log_info "Planning Terraform changes..."
terraform plan -out=tfplan

echo ""
log_warn "Review the Terraform plan above."
read -p "Do you want to apply these changes? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    log_warn "Deployment cancelled"
    rm -f tfplan
    exit 0
fi

log_info "Applying Terraform configuration..."
terraform apply tfplan
rm -f tfplan

log_info "  ✓ Infrastructure deployed"

# ==========================================
# STEP 5: Configure SSM Parameters
# ==========================================
echo ""
log_info "STEP 5: Configuring SSM parameters..."

# Get bucket names from Terraform outputs
ARTIFACTS_BUCKET=$(terraform output -raw ml_artifacts_bucket 2>/dev/null || echo "")
EFS_ID=$(terraform output -raw efs_file_system_id 2>/dev/null || echo "")

if [ -n "$ARTIFACTS_BUCKET" ]; then
    log_info "Setting S3 artifacts bucket..."
    aws ssm put-parameter --name /bitoguard/ml-pipeline/s3/artifacts_bucket \
        --value "$ARTIFACTS_BUCKET" --type String --overwrite >/dev/null
fi

if [ -n "$EFS_ID" ]; then
    log_info "Setting EFS file system ID..."
    aws ssm put-parameter --name /bitoguard/ml-pipeline/efs/file_system_id \
        --value "$EFS_ID" --type String --overwrite >/dev/null
fi

# Training hyperparameters
log_info "Setting training hyperparameters..."
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/n_estimators --value "500" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/learning_rate --value "0.05" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/max_depth --value "7" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/lgbm/num_leaves --value "63" --type String --overwrite >/dev/null

aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/iterations --value "500" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/learning_rate --value "0.05" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/catboost/depth --value "6" --type String --overwrite >/dev/null

aws ssm put-parameter --name /bitoguard/ml-pipeline/training/iforest/n_estimators --value "200" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/training/iforest/contamination --value "0.1" --type String --overwrite >/dev/null

# Thresholds
log_info "Setting thresholds..."
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/feature_drift_kl --value "0.1" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/prediction_drift_percentage --value "0.15" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/thresholds/alert_risk_score --value "0.7" --type String --overwrite >/dev/null

# Resource configs
log_info "Setting resource configurations..."
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/sagemaker_instance_type --value "ml.m5.xlarge" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/sagemaker_max_runtime_seconds --value "3600" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/ecs_task_cpu --value "2048" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/resources/ecs_task_memory --value "4096" --type String --overwrite >/dev/null

# Schedules
log_info "Setting schedules..."
aws ssm put-parameter --name /bitoguard/ml-pipeline/scheduling/daily_full_pipeline_cron --value "cron(0 2 * * ? *)" --type String --overwrite >/dev/null
aws ssm put-parameter --name /bitoguard/ml-pipeline/scheduling/incremental_refresh_cron --value "cron(0 8,12,16,20 * * ? *)" --type String --overwrite >/dev/null

log_info "  ✓ SSM parameters configured"

# ==========================================
# STEP 6: Display Deployment Information
# ==========================================
echo ""
echo "=========================================="
log_info "Deployment Complete!"
echo "=========================================="
echo ""

# Get outputs
ALB_URL=$(terraform output -raw alb_url 2>/dev/null || echo "N/A")
STATE_MACHINE_ARN=$(terraform output -raw ml_pipeline_state_machine_arn 2>/dev/null || echo "N/A")
TRIGGER_URL=$(terraform output -raw manual_trigger_function_url 2>/dev/null || echo "N/A")
DASHBOARD_NAME=$(terraform output -raw ml_pipeline_dashboard_name 2>/dev/null || echo "N/A")

echo "Application URLs:"
echo "  Frontend: http://$ALB_URL"
echo "  Backend API: http://$ALB_URL/api"
echo ""
echo "ML Pipeline Resources:"
echo "  State Machine: $STATE_MACHINE_ARN"
echo "  Manual Trigger: $TRIGGER_URL"
echo "  S3 Artifacts: s3://$ARTIFACTS_BUCKET"
echo "  EFS ID: $EFS_ID"
echo ""
echo "Monitoring:"
echo "  Dashboard: https://console.aws.amazon.com/cloudwatch/home?region=$AWS_REGION#dashboards:name=$DASHBOARD_NAME"
echo "  Logs: https://console.aws.amazon.com/cloudwatch/home?region=$AWS_REGION#logsV2:log-groups"
echo ""

# ==========================================
# STEP 7: Health Check
# ==========================================
log_info "Running health checks..."
sleep 10

# Check if ALB is responding
if [ "$ALB_URL" != "N/A" ]; then
    if curl -s -o /dev/null -w "%{http_code}" "http://$ALB_URL/api/health" | grep -q "200"; then
        log_info "  ✓ Backend API is healthy"
    else
        log_warn "  ⚠ Backend API not responding yet (may take a few minutes)"
    fi
fi

# ==========================================
# STEP 8: Next Steps
# ==========================================
echo ""
echo "Next Steps:"
echo "=========================================="
echo "1. Subscribe to SNS topics for alerts:"
echo "   aws sns subscribe --topic-arn <topic-arn> --protocol email --notification-endpoint your-email@example.com"
echo ""
echo "2. Test the ML pipeline manually:"
echo "   curl -X POST \"$TRIGGER_URL\" \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"execution_type\":\"full\",\"skip_training\":false,\"model_types\":[\"lgbm\",\"catboost\",\"iforest\"]}'"
echo ""
echo "3. Monitor pipeline execution:"
echo "   aws stepfunctions list-executions --state-machine-arn \"$STATE_MACHINE_ARN\" --max-results 5"
echo ""
echo "4. View CloudWatch logs:"
echo "   aws logs tail /ecs/bitoguard-prod-ml-pipeline --follow"
echo ""
echo "5. Check SageMaker training jobs:"
echo "   aws sagemaker list-training-jobs --sort-by CreationTime --sort-order Descending --max-results 5"
echo ""
echo "=========================================="
log_info "Deployment script completed successfully!"
echo "=========================================="
