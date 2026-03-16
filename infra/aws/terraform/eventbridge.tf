# EventBridge Rules for ML Pipeline Scheduling

# Daily Full Pipeline Rule
resource "aws_cloudwatch_event_rule" "daily_full_pipeline" {
  name                = "${local.name_prefix}-daily-full-pipeline"
  description         = "Trigger full ML pipeline daily at 2 AM UTC"
  schedule_expression = "cron(0 2 * * ? *)"

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-daily-full-pipeline"
  })
}

resource "aws_cloudwatch_event_target" "daily_full_pipeline" {
  rule      = aws_cloudwatch_event_rule.daily_full_pipeline.name
  target_id = "MLPipelineStateMachine"
  arn       = aws_sfn_state_machine.ml_pipeline.arn
  role_arn  = aws_iam_role.eventbridge_stepfunctions.arn

  input = jsonencode({
    execution_type = "full"
    skip_training  = false
    model_types    = ["lgbm", "catboost", "iforest"]
    triggered_by   = "scheduled"
  })
}

# Incremental Refresh Rule
resource "aws_cloudwatch_event_rule" "incremental_refresh" {
  name                = "${local.name_prefix}-incremental-refresh"
  description         = "Trigger incremental refresh every 4 hours"
  schedule_expression = "cron(0 8,12,16,20 * * ? *)"

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-incremental-refresh"
  })
}

resource "aws_cloudwatch_event_target" "incremental_refresh" {
  rule      = aws_cloudwatch_event_rule.incremental_refresh.name
  target_id = "MLPipelineStateMachine"
  arn       = aws_sfn_state_machine.ml_pipeline.arn
  role_arn  = aws_iam_role.eventbridge_stepfunctions.arn

  input = jsonencode({
    execution_type = "incremental"
    skip_training  = true
    triggered_by   = "scheduled"
  })
}

# Outputs
output "daily_pipeline_rule_arn" {
  description = "ARN of the daily pipeline EventBridge rule"
  value       = aws_cloudwatch_event_rule.daily_full_pipeline.arn
}

output "incremental_refresh_rule_arn" {
  description = "ARN of the incremental refresh EventBridge rule"
  value       = aws_cloudwatch_event_rule.incremental_refresh.arn
}
