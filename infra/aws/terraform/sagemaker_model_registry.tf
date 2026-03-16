# SageMaker Model Registry Configuration

# Model Package Groups for each model type
resource "aws_sagemaker_model_package_group" "lgbm" {
  model_package_group_name        = "${local.name_prefix}-lgbm-models"
  model_package_group_description = "LightGBM fraud detection models for BitoGuard"

  tags = merge(local.common_tags, {
    Name      = "${local.name_prefix}-lgbm-models"
    ModelType = "lgbm"
  })
}

resource "aws_sagemaker_model_package_group" "catboost" {
  model_package_group_name        = "${local.name_prefix}-catboost-models"
  model_package_group_description = "CatBoost ensemble models for BitoGuard"

  tags = merge(local.common_tags, {
    Name      = "${local.name_prefix}-catboost-models"
    ModelType = "catboost"
  })
}

resource "aws_sagemaker_model_package_group" "iforest" {
  model_package_group_name        = "${local.name_prefix}-iforest-models"
  model_package_group_description = "IsolationForest anomaly detection models for BitoGuard"

  tags = merge(local.common_tags, {
    Name      = "${local.name_prefix}-iforest-models"
    ModelType = "iforest"
  })
}

resource "aws_sagemaker_model_package_group" "stacker" {
  model_package_group_name        = "${local.name_prefix}-stacker-models"
  model_package_group_description = "Ensemble stacker models (CatBoost + LightGBM + LR) with 5-fold CV for BitoGuard"

  tags = merge(local.common_tags, {
    Name      = "${local.name_prefix}-stacker-models"
    ModelType = "stacker"
  })
}

# SSM Parameters for model registry configuration
resource "aws_ssm_parameter" "model_approval_required" {
  name        = "/bitoguard/ml-pipeline/model-registry/approval_required"
  description = "Whether model approval is required before deployment"
  type        = "String"
  value       = "true"
  
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-model-approval-required"
  })
}

resource "aws_ssm_parameter" "model_retention_days" {
  name        = "/bitoguard/ml-pipeline/model-registry/retention_days"
  description = "Number of days to retain model versions"
  type        = "String"
  value       = "90"
  
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-model-retention-days"
  })
}

# Outputs
output "model_package_groups" {
  description = "Model package group names"
  value = {
    lgbm     = aws_sagemaker_model_package_group.lgbm.model_package_group_name
    catboost = aws_sagemaker_model_package_group.catboost.model_package_group_name
    iforest  = aws_sagemaker_model_package_group.iforest.model_package_group_name
    stacker  = aws_sagemaker_model_package_group.stacker.model_package_group_name
  }
}

output "model_package_group_arns" {
  description = "Model package group ARNs"
  value = {
    lgbm     = aws_sagemaker_model_package_group.lgbm.arn
    catboost = aws_sagemaker_model_package_group.catboost.arn
    iforest  = aws_sagemaker_model_package_group.iforest.arn
    stacker  = aws_sagemaker_model_package_group.stacker.arn
  }
}
