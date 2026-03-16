# Lambda Functions for ML Pipeline

# Drift Detector Lambda
resource "aws_lambda_function" "drift_detector" {
  filename         = "${path.module}/../lambda/drift_detector.zip"
  function_name    = "${local.name_prefix}-drift-detector"
  role            = aws_iam_role.drift_detector_lambda.arn
  handler         = "lambda_function.lambda_handler"
  source_code_hash = filebase64sha256("${path.module}/../lambda/drift_detector.zip")
  runtime         = "python3.11"
  timeout         = 300  # 5 minutes
  memory_size     = 1024  # 1GB

  environment {
    variables = {
      DRIFT_ALERTS_TOPIC_ARN = aws_sns_topic.drift_alerts.arn
    }
  }

  layers = [
    "arn:aws:lambda:${var.aws_region}:336392948345:layer:AWSSDKPandas-Python311:20"
  ]

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-drift-detector"
  })
}

# Config Validator Lambda
resource "aws_lambda_function" "config_validator" {
  filename         = "${path.module}/../lambda/config_validator.zip"
  function_name    = "${local.name_prefix}-config-validator"
  role            = aws_iam_role.config_validator_lambda.arn
  handler         = "lambda_function.lambda_handler"
  source_code_hash = filebase64sha256("${path.module}/../lambda/config_validator.zip")
  runtime         = "python3.11"
  timeout         = 60
  memory_size     = 256

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-config-validator"
  })
}

# Manual Trigger Lambda
resource "aws_lambda_function" "manual_trigger" {
  filename         = "${path.module}/../lambda/manual_trigger.zip"
  function_name    = "${local.name_prefix}-manual-trigger"
  role            = aws_iam_role.manual_trigger_lambda.arn
  handler         = "lambda_function.lambda_handler"
  source_code_hash = filebase64sha256("${path.module}/../lambda/manual_trigger.zip")
  runtime         = "python3.11"
  timeout         = 30
  memory_size     = 128

  environment {
    variables = {
      STATE_MACHINE_ARN = aws_sfn_state_machine.ml_pipeline.arn
    }
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-manual-trigger"
  })
}

# Lambda Function URL for Manual Trigger (optional - for API access)
resource "aws_lambda_function_url" "manual_trigger" {
  function_name      = aws_lambda_function.manual_trigger.function_name
  authorization_type = "AWS_IAM"

  cors {
    allow_credentials = true
    allow_origins     = ["*"]
    allow_methods     = ["POST"]
    allow_headers     = ["*"]
    max_age           = 86400
  }
}

# Tuning Analyzer Lambda Function
resource "aws_lambda_function" "tuning_analyzer" {
  filename         = data.archive_file.tuning_analyzer_lambda.output_path
  function_name    = "${local.name_prefix}-tuning-analyzer"
  role            = aws_iam_role.tuning_analyzer_lambda.arn
  handler         = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.tuning_analyzer_lambda.output_base64sha256
  runtime         = "python3.11"
  timeout         = 300
  memory_size     = 512

  environment {
    variables = {
      LOG_LEVEL = "INFO"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-analyzer"
  })
}

data "archive_file" "tuning_analyzer_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/tuning_analyzer"
  output_path = "${path.module}/../lambda/tuning_analyzer.zip"
}

# CloudWatch Log Group for Tuning Analyzer
resource "aws_cloudwatch_log_group" "tuning_analyzer" {
  name              = "/aws/lambda/${aws_lambda_function.tuning_analyzer.function_name}"
  retention_in_days = 30

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-analyzer-logs"
  })
}

# Outputs
output "tuning_analyzer_lambda_arn" {
  description = "ARN of the tuning analyzer Lambda function"
  value       = aws_lambda_function.tuning_analyzer.arn
}

output "config_validator_lambda_arn" {
  description = "ARN of the config validator Lambda function"
  value       = aws_lambda_function.config_validator.arn
}

output "manual_trigger_lambda_arn" {
  description = "ARN of the manual trigger Lambda function"
  value       = aws_lambda_function.manual_trigger.arn
}

output "manual_trigger_function_url" {
  description = "Function URL for manual trigger Lambda"
  value       = aws_lambda_function_url.manual_trigger.function_url
}


# Model Registry Lambda Function
resource "aws_lambda_function" "model_registry" {
  filename         = data.archive_file.model_registry_lambda.output_path
  function_name    = "${local.name_prefix}-model-registry"
  role            = aws_iam_role.model_registry_lambda.arn
  handler         = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.model_registry_lambda.output_base64sha256
  runtime         = "python3.11"
  timeout         = 300
  memory_size     = 512

  environment {
    variables = {
      LOG_LEVEL = "INFO"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-model-registry"
  })
}

data "archive_file" "model_registry_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/model_registry"
  output_path = "${path.module}/../lambda/model_registry.zip"
}

# CloudWatch Log Group for Model Registry
resource "aws_cloudwatch_log_group" "model_registry" {
  name              = "/aws/lambda/${aws_lambda_function.model_registry.function_name}"
  retention_in_days = 30

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-model-registry-logs"
  })
}

# Outputs
output "model_registry_lambda_arn" {
  description = "ARN of the model registry Lambda function"
  value       = aws_lambda_function.model_registry.arn
}
