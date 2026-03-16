# SageMaker Hyperparameter Tuning Configuration

# Hyperparameter ranges for LightGBM
locals {
  lgbm_hyperparameter_ranges = {
    continuous_parameter_ranges = [
      {
        name         = "learning_rate"
        min_value    = "0.01"
        max_value    = "0.3"
        scaling_type = "Logarithmic"
      },
      {
        name         = "subsample"
        min_value    = "0.6"
        max_value    = "1.0"
        scaling_type = "Linear"
      },
      {
        name         = "colsample_bytree"
        min_value    = "0.6"
        max_value    = "1.0"
        scaling_type = "Linear"
      },
      {
        name         = "reg_alpha"
        min_value    = "0.0"
        max_value    = "1.0"
        scaling_type = "Linear"
      },
      {
        name         = "reg_lambda"
        min_value    = "0.0"
        max_value    = "1.0"
        scaling_type = "Linear"
      }
    ]
    
    integer_parameter_ranges = [
      {
        name         = "num_leaves"
        min_value    = "20"
        max_value    = "100"
        scaling_type = "Linear"
      },
      {
        name         = "n_estimators"
        min_value    = "100"
        max_value    = "500"
        scaling_type = "Linear"
      },
      {
        name         = "min_data_in_leaf"
        min_value    = "10"
        max_value    = "100"
        scaling_type = "Linear"
      },
      {
        name         = "max_depth"
        min_value    = "3"
        max_value    = "12"
        scaling_type = "Linear"
      }
    ]
  }
  
  # Hyperparameter ranges for CatBoost
  catboost_hyperparameter_ranges = {
    continuous_parameter_ranges = [
      {
        name         = "learning_rate"
        min_value    = "0.01"
        max_value    = "0.3"
        scaling_type = "Logarithmic"
      },
      {
        name         = "subsample"
        min_value    = "0.6"
        max_value    = "1.0"
        scaling_type = "Linear"
      },
      {
        name         = "colsample_bytree"
        min_value    = "0.6"
        max_value    = "1.0"
        scaling_type = "Linear"
      },
      {
        name         = "l2_leaf_reg"
        min_value    = "1.0"
        max_value    = "10.0"
        scaling_type = "Linear"
      }
    ]
    
    integer_parameter_ranges = [
      {
        name         = "depth"
        min_value    = "4"
        max_value    = "10"
        scaling_type = "Linear"
      },
      {
        name         = "n_estimators"
        min_value    = "100"
        max_value    = "500"
        scaling_type = "Linear"
      }
    ]
  }
  
  # Metric definitions for tuning
  metric_definitions = [
    {
      name  = "precision_at_100"
      regex = "precision_at_100: ([0-9\\\\.]+)"
    },
    {
      name  = "valid_logloss"
      regex = "valid_logloss: ([0-9\\\\.]+)"
    },
    {
      name  = "auc"
      regex = "auc: ([0-9\\\\.]+)"
    }
  ]
}

# SSM Parameters for tuning configuration
resource "aws_ssm_parameter" "tuning_enabled" {
  name        = "/bitoguard/ml-pipeline/tuning/enabled"
  description = "Enable hyperparameter tuning"
  type        = "String"
  value       = "false"
  
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-enabled"
  })
}

resource "aws_ssm_parameter" "tuning_max_jobs" {
  name        = "/bitoguard/ml-pipeline/tuning/max_jobs"
  description = "Maximum number of training jobs for tuning"
  type        = "String"
  value       = "20"
  
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-max-jobs"
  })
}

resource "aws_ssm_parameter" "tuning_max_parallel_jobs" {
  name        = "/bitoguard/ml-pipeline/tuning/max_parallel_jobs"
  description = "Maximum number of parallel training jobs for tuning"
  type        = "String"
  value       = "3"
  
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-max-parallel-jobs"
  })
}

resource "aws_ssm_parameter" "tuning_strategy" {
  name        = "/bitoguard/ml-pipeline/tuning/strategy"
  description = "Hyperparameter tuning strategy (Bayesian, Random, Grid)"
  type        = "String"
  value       = "Bayesian"
  
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-strategy"
  })
}

resource "aws_ssm_parameter" "tuning_objective_metric" {
  name        = "/bitoguard/ml-pipeline/tuning/objective_metric"
  description = "Objective metric for hyperparameter tuning"
  type        = "String"
  value       = "precision_at_100"
  
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-objective-metric"
  })
}

resource "aws_ssm_parameter" "tuning_objective_type" {
  name        = "/bitoguard/ml-pipeline/tuning/objective_type"
  description = "Objective type for hyperparameter tuning (Maximize or Minimize)"
  type        = "String"
  value       = "Maximize"
  
  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-objective-type"
  })
}

# S3 bucket for tuning results
resource "aws_s3_bucket_lifecycle_configuration" "tuning_results_lifecycle" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "archive-tuning-results"
    status = "Enabled"

    filter {
      prefix = "tuning-results/"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}

# Outputs
output "tuning_configuration" {
  description = "Hyperparameter tuning configuration"
  value = {
    lgbm_ranges     = local.lgbm_hyperparameter_ranges
    catboost_ranges = local.catboost_hyperparameter_ranges
    metric_definitions = local.metric_definitions
  }
}
