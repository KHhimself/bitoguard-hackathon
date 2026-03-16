# ML Pipeline Infrastructure
# S3 bucket lifecycle policies for ML artifacts

resource "aws_s3_bucket_lifecycle_configuration" "ml_artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "archive-old-models"
    status = "Enabled"

    filter {
      prefix = "models/"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "GLACIER"
    }
  }

  rule {
    id     = "retain-recent-models"
    status = "Enabled"

    filter {
      prefix = "models/"
    }

    noncurrent_version_expiration {
      newer_noncurrent_versions = 10
      noncurrent_days           = 90
    }
  }

  rule {
    id     = "intelligent-tiering-features"
    status = "Enabled"

    filter {
      prefix = "features/"
    }

    transition {
      days          = 0
      storage_class = "INTELLIGENT_TIERING"
    }
  }
}

# SNS Topics for ML Pipeline Notifications
resource "aws_sns_topic" "ml_pipeline_notifications" {
  name = "${local.name_prefix}-ml-pipeline-notifications"

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-ml-pipeline-notifications"
  })
}

resource "aws_sns_topic" "drift_alerts" {
  name = "${local.name_prefix}-drift-alerts"

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-drift-alerts"
  })
}

resource "aws_sns_topic" "critical_errors" {
  name = "${local.name_prefix}-critical-errors"

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-critical-errors"
  })
}

# SNS Topic Subscriptions (email - to be configured)
resource "aws_sns_topic_subscription" "ml_pipeline_email" {
  count     = var.ml_notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.ml_pipeline_notifications.arn
  protocol  = "email"
  endpoint  = var.ml_notification_email
}

resource "aws_sns_topic_subscription" "drift_alerts_email" {
  count     = var.ml_notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.drift_alerts.arn
  protocol  = "email"
  endpoint  = var.ml_notification_email
}

resource "aws_sns_topic_subscription" "critical_errors_email" {
  count     = var.ml_notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.critical_errors.arn
  protocol  = "email"
  endpoint  = var.ml_notification_email
}

# Outputs for ML Pipeline
output "ml_artifacts_bucket" {
  description = "S3 bucket for ML artifacts"
  value       = aws_s3_bucket.artifacts.id
}

output "ml_pipeline_log_group" {
  description = "CloudWatch log group for ML pipeline"
  value       = "/ecs/${local.name_prefix}-ml-pipeline"
}

output "ml_pipeline_notifications_topic" {
  description = "SNS topic for ML pipeline notifications"
  value       = aws_sns_topic.ml_pipeline_notifications.arn
}

output "drift_alerts_topic" {
  description = "SNS topic for drift alerts"
  value       = aws_sns_topic.drift_alerts.arn
}

output "critical_errors_topic" {
  description = "SNS topic for critical errors"
  value       = aws_sns_topic.critical_errors.arn
}
