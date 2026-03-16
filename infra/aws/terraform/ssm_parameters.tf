# Systems Manager Parameter Store for ML Pipeline Configuration

# Pipeline Scheduling
resource "aws_ssm_parameter" "schedule_daily_full" {
  name  = "/bitoguard/ml-pipeline/schedule/daily-full"
  type  = "String"
  value = var.ml_daily_schedule

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-schedule-daily-full"
  })
}

resource "aws_ssm_parameter" "schedule_incremental" {
  name  = "/bitoguard/ml-pipeline/schedule/incremental"
  type  = "String"
  value = var.ml_incremental_schedule

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-schedule-incremental"
  })
}

# Training Hyperparameters - LightGBM
resource "aws_ssm_parameter" "lgbm_n_estimators" {
  name  = "/bitoguard/ml-pipeline/training/lgbm/n_estimators"
  type  = "String"
  value = "250"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "lgbm_learning_rate" {
  name  = "/bitoguard/ml-pipeline/training/lgbm/learning_rate"
  type  = "String"
  value = "0.05"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "lgbm_num_leaves" {
  name  = "/bitoguard/ml-pipeline/training/lgbm/num_leaves"
  type  = "String"
  value = "31"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "lgbm_subsample" {
  name  = "/bitoguard/ml-pipeline/training/lgbm/subsample"
  type  = "String"
  value = "0.9"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "lgbm_colsample_bytree" {
  name  = "/bitoguard/ml-pipeline/training/lgbm/colsample_bytree"
  type  = "String"
  value = "0.9"

  tags = local.common_tags
}

# Training Hyperparameters - CatBoost
resource "aws_ssm_parameter" "catboost_iterations" {
  name  = "/bitoguard/ml-pipeline/training/catboost/iterations"
  type  = "String"
  value = "500"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "catboost_learning_rate" {
  name  = "/bitoguard/ml-pipeline/training/catboost/learning_rate"
  type  = "String"
  value = "0.03"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "catboost_depth" {
  name  = "/bitoguard/ml-pipeline/training/catboost/depth"
  type  = "String"
  value = "6"

  tags = local.common_tags
}

# Training Hyperparameters - IsolationForest
resource "aws_ssm_parameter" "iforest_n_estimators" {
  name  = "/bitoguard/ml-pipeline/training/iforest/n_estimators"
  type  = "String"
  value = "100"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "iforest_contamination" {
  name  = "/bitoguard/ml-pipeline/training/iforest/contamination"
  type  = "String"
  value = "0.1"

  tags = local.common_tags
}

# Alert Thresholds
resource "aws_ssm_parameter" "alert_threshold" {
  name  = "/bitoguard/ml-pipeline/scoring/alert_threshold"
  type  = "String"
  value = "80"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "high_risk_threshold" {
  name  = "/bitoguard/ml-pipeline/scoring/high_risk_threshold"
  type  = "String"
  value = "60"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "critical_risk_threshold" {
  name  = "/bitoguard/ml-pipeline/scoring/critical_risk_threshold"
  type  = "String"
  value = "80"

  tags = local.common_tags
}

# Drift Detection
resource "aws_ssm_parameter" "drift_kl_threshold" {
  name  = "/bitoguard/ml-pipeline/drift/kl_threshold"
  type  = "String"
  value = "0.1"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "drift_prediction_threshold" {
  name  = "/bitoguard/ml-pipeline/drift/prediction_threshold"
  type  = "String"
  value = "15"

  tags = local.common_tags
}

# Resource Configuration - Sync
resource "aws_ssm_parameter" "sync_cpu" {
  name  = "/bitoguard/ml-pipeline/resources/sync/cpu"
  type  = "String"
  value = "1024"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "sync_memory" {
  name  = "/bitoguard/ml-pipeline/resources/sync/memory"
  type  = "String"
  value = "2048"

  tags = local.common_tags
}

# Resource Configuration - Features
resource "aws_ssm_parameter" "features_cpu" {
  name  = "/bitoguard/ml-pipeline/resources/features/cpu"
  type  = "String"
  value = "2048"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "features_memory" {
  name  = "/bitoguard/ml-pipeline/resources/features/memory"
  type  = "String"
  value = "4096"

  tags = local.common_tags
}

# Resource Configuration - Scoring
resource "aws_ssm_parameter" "scoring_cpu" {
  name  = "/bitoguard/ml-pipeline/resources/scoring/cpu"
  type  = "String"
  value = "2048"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "scoring_memory" {
  name  = "/bitoguard/ml-pipeline/resources/scoring/memory"
  type  = "String"
  value = "4096"

  tags = local.common_tags
}

# S3 Paths
resource "aws_ssm_parameter" "s3_bucket" {
  name  = "/bitoguard/ml-pipeline/s3/bucket"
  type  = "String"
  value = aws_s3_bucket.artifacts.id

  tags = local.common_tags
}

resource "aws_ssm_parameter" "s3_models_prefix" {
  name  = "/bitoguard/ml-pipeline/s3/models_prefix"
  type  = "String"
  value = "models/"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "s3_features_prefix" {
  name  = "/bitoguard/ml-pipeline/s3/features_prefix"
  type  = "String"
  value = "features/"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "s3_drift_prefix" {
  name  = "/bitoguard/ml-pipeline/s3/drift_prefix"
  type  = "String"
  value = "drift_reports/"

  tags = local.common_tags
}

# Notification
resource "aws_ssm_parameter" "sns_topic" {
  name  = "/bitoguard/ml-pipeline/notifications/sns_topic"
  type  = "String"
  value = aws_sns_topic.ml_pipeline_notifications.arn

  tags = local.common_tags
}

# EFS Configuration
resource "aws_ssm_parameter" "efs_file_system_id" {
  name  = "/bitoguard/ml-pipeline/efs/file_system_id"
  type  = "String"
  value = aws_efs_file_system.bitoguard.id

  tags = local.common_tags
}

# Outputs
output "ssm_parameter_prefix" {
  description = "SSM Parameter Store prefix for ML pipeline"
  value       = "/bitoguard/ml-pipeline/"
}
