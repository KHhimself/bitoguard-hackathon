resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.name_prefix}-backend"
  retention_in_days = 7

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-backend-logs"
  })
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.name_prefix}-frontend"
  retention_in_days = 7

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-frontend-logs"
  })
}

resource "aws_cloudwatch_metric_alarm" "backend_cpu" {
  alarm_name          = "${local.name_prefix}-backend-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "This metric monitors backend CPU utilization"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.backend.name
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "backend_memory" {
  alarm_name          = "${local.name_prefix}-backend-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "This metric monitors backend memory utilization"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.backend.name
  }

  tags = local.common_tags
}

# ML Pipeline CloudWatch Resources

resource "aws_cloudwatch_log_group" "ml_pipeline" {
  name              = "/aws/stepfunctions/${local.name_prefix}-ml-pipeline"
  retention_in_days = 30

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-ml-pipeline-logs"
  })
}

resource "aws_cloudwatch_log_group" "sagemaker_processing" {
  name              = "/aws/sagemaker/ProcessingJobs"
  retention_in_days = 30

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-sagemaker-processing-logs"
  })
}

resource "aws_cloudwatch_log_group" "sagemaker_training" {
  name              = "/aws/sagemaker/TrainingJobs"
  retention_in_days = 30

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-sagemaker-training-logs"
  })
}

resource "aws_cloudwatch_log_group" "sagemaker_endpoints" {
  name              = "/aws/sagemaker/Endpoints"
  retention_in_days = 30

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-sagemaker-endpoints-logs"
  })
}

# ML Pipeline Dashboard
resource "aws_cloudwatch_dashboard" "ml_pipeline" {
  dashboard_name = "${local.name_prefix}-ml-pipeline"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/States", "ExecutionsFailed", { stat = "Sum", label = "Failed Executions" }],
            [".", "ExecutionsSucceeded", { stat = "Sum", label = "Successful Executions" }],
            [".", "ExecutionTime", { stat = "Average", label = "Avg Execution Time (ms)" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "Step Functions - Pipeline Executions"
          yAxis = {
            left = {
              min = 0
            }
          }
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/SageMaker", "TrainingJobsFailed", { stat = "Sum", label = "Failed Training Jobs" }],
            [".", "TrainingJobsSucceeded", { stat = "Sum", label = "Successful Training Jobs" }],
            [".", "TrainingTime", { stat = "Average", label = "Avg Training Time (s)" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "SageMaker - Training Jobs"
          yAxis = {
            left = {
              min = 0
            }
          }
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/SageMaker", "ProcessingJobsFailed", { stat = "Sum", label = "Failed Processing Jobs" }],
            [".", "ProcessingJobsSucceeded", { stat = "Sum", label = "Successful Processing Jobs" }],
            [".", "ProcessingJobDuration", { stat = "Average", label = "Avg Duration (s)" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "SageMaker - Processing Jobs"
          yAxis = {
            left = {
              min = 0
            }
          }
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/SageMaker", "HyperParameterTuningJobsFailed", { stat = "Sum", label = "Failed Tuning Jobs" }],
            [".", "HyperParameterTuningJobsSucceeded", { stat = "Sum", label = "Successful Tuning Jobs" }],
            [".", "BestObjectiveMetric", { stat = "Maximum", label = "Best Metric Value" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "SageMaker - Hyperparameter Tuning"
          yAxis = {
            left = {
              min = 0
            }
          }
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/SageMaker", "ModelLatency", { stat = "Average", label = "Avg Latency (ms)" }],
            ["...", { stat = "p95", label = "P95 Latency (ms)" }],
            [".", "Invocations", { stat = "Sum", label = "Total Invocations" }],
            [".", "InvocationErrors", { stat = "Sum", label = "Invocation Errors" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "SageMaker - Endpoint Performance"
          yAxis = {
            left = {
              min = 0
            }
          }
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/SageMaker", "TransformJobsFailed", { stat = "Sum", label = "Failed Transform Jobs" }],
            [".", "TransformJobsSucceeded", { stat = "Sum", label = "Successful Transform Jobs" }],
            [".", "TransformJobDuration", { stat = "Average", label = "Avg Duration (s)" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "SageMaker - Batch Transform Jobs"
          yAxis = {
            left = {
              min = 0
            }
          }
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["BitoGuard/MLPipeline", "FeatureDriftCount", { stat = "Sum", label = "Features with Drift" }],
            [".", "PredictionDriftPercentage", { stat = "Average", label = "Prediction Drift %" }],
            [".", "AlertCount", { stat = "Sum", label = "Alerts Generated" }]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "ML Pipeline - Drift and Alerts"
          yAxis = {
            left = {
              min = 0
            }
          }
        }
      },
      {
        type = "log"
        properties = {
          query   = "SOURCE '/aws/stepfunctions/${local.name_prefix}-ml-pipeline' | fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20"
          region  = var.aws_region
          title   = "Recent Pipeline Errors"
          stacked = false
        }
      }
    ]
  })
}

# ML Pipeline Alarms

resource "aws_cloudwatch_metric_alarm" "pipeline_execution_failed" {
  alarm_name          = "${local.name_prefix}-pipeline-execution-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "Alert when ML pipeline execution fails"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.critical_errors.arn]

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.ml_pipeline.arn
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "pipeline_duration_high" {
  alarm_name          = "${local.name_prefix}-pipeline-duration-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "ExecutionTime"
  namespace           = "AWS/States"
  period              = "300"
  statistic           = "Average"
  threshold           = "7200000" # 2 hours in milliseconds
  alarm_description   = "Alert when ML pipeline execution exceeds 2 hours"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.ml_pipeline_notifications.arn]

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.ml_pipeline.arn
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "sagemaker_processing_failed" {
  alarm_name          = "${local.name_prefix}-sagemaker-processing-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "ProcessingJobsFailed"
  namespace           = "AWS/SageMaker"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "Alert when SageMaker processing job fails"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.critical_errors.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "sagemaker_training_failed" {
  alarm_name          = "${local.name_prefix}-sagemaker-training-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "TrainingJobsFailed"
  namespace           = "AWS/SageMaker"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "Alert when SageMaker training job fails"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.critical_errors.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "sagemaker_tuning_failed" {
  alarm_name          = "${local.name_prefix}-sagemaker-tuning-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "HyperParameterTuningJobsFailed"
  namespace           = "AWS/SageMaker"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "Alert when SageMaker hyperparameter tuning job fails"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.critical_errors.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "sagemaker_endpoint_latency_high" {
  alarm_name          = "${local.name_prefix}-sagemaker-endpoint-latency-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ModelLatency"
  namespace           = "AWS/SageMaker"
  period              = "300"
  statistic           = "Average"
  threshold           = "200" # 200ms average
  alarm_description   = "Alert when SageMaker endpoint latency exceeds 200ms at p95"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.ml_pipeline_notifications.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "sagemaker_batch_transform_failed" {
  alarm_name          = "${local.name_prefix}-sagemaker-batch-transform-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "TransformJobsFailed"
  namespace           = "AWS/SageMaker"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "Alert when SageMaker batch transform job fails"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.critical_errors.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "feature_drift_high" {
  alarm_name          = "${local.name_prefix}-feature-drift-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "FeatureDriftCount"
  namespace           = "BitoGuard/MLPipeline"
  period              = "300"
  statistic           = "Sum"
  threshold           = "5"
  alarm_description   = "Alert when more than 5 features show drift"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.drift_alerts.arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "prediction_drift_high" {
  alarm_name          = "${local.name_prefix}-prediction-drift-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "PredictionDriftPercentage"
  namespace           = "BitoGuard/MLPipeline"
  period              = "300"
  statistic           = "Average"
  threshold           = "15"
  alarm_description   = "Alert when prediction drift exceeds 15%"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.drift_alerts.arn]

  tags = local.common_tags
}

# Outputs
output "ml_pipeline_dashboard_url" {
  description = "URL to ML Pipeline CloudWatch Dashboard"
  value       = "https://console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.ml_pipeline.dashboard_name}"
}
