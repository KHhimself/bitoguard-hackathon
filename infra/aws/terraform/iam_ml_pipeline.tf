# IAM Roles and Policies for ML Pipeline

# ML Pipeline Task Role (for ECS tasks running sync, features, scoring)
resource "aws_iam_role" "ml_pipeline_task" {
  name               = "${local.name_prefix}-ml-pipeline-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-ml-pipeline-task-role"
  })
}

data "aws_iam_policy_document" "ml_pipeline_task" {
  # S3 access for ML artifacts
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
      "s3:DeleteObject"
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*"
    ]
  }

  # EFS access for DuckDB
  statement {
    actions = [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientWrite",
      "elasticfilesystem:DescribeFileSystems"
    ]
    resources = [aws_efs_file_system.bitoguard.arn]
  }

  # SSM Parameter Store access
  statement {
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath"
    ]
    resources = [
      "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/bitoguard/ml-pipeline/*"
    ]
  }

  # CloudWatch metrics
  statement {
    actions = [
      "cloudwatch:PutMetricData"
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["BitoGuard/MLPipeline"]
    }
  }

  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "${aws_cloudwatch_log_group.ml_pipeline.arn}:*"
    ]
  }

  # Secrets Manager for API keys
  statement {
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = [
      aws_secretsmanager_secret.bitoguard_api_key.arn
    ]
  }
}

resource "aws_iam_role_policy" "ml_pipeline_task" {
  name   = "${local.name_prefix}-ml-pipeline-task-policy"
  role   = aws_iam_role.ml_pipeline_task.id
  policy = data.aws_iam_policy_document.ml_pipeline_task.json
}

# SageMaker Execution Role
resource "aws_iam_role" "sagemaker_execution" {
  name = "${local.name_prefix}-sagemaker-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "sagemaker.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-sagemaker-execution-role"
  })
}

data "aws_iam_policy_document" "sagemaker_execution" {
  # S3 access for training data and model artifacts
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*"
    ]
  }

  # ECR access for training container
  statement {
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage"
    ]
    resources = ["*"]
  }

  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/sagemaker/*"
    ]
  }

  # CloudWatch Metrics
  statement {
    actions = [
      "cloudwatch:PutMetricData"
    ]
    resources = ["*"]
  }

  # EFS access for DuckDB (processing jobs)
  statement {
    actions = [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientWrite",
      "elasticfilesystem:DescribeFileSystems",
      "elasticfilesystem:DescribeMountTargets"
    ]
    resources = [aws_efs_file_system.bitoguard.arn]
  }

  # SSM Parameter Store (for processing and training jobs)
  statement {
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath"
    ]
    resources = [
      "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/bitoguard/ml-pipeline/*"
    ]
  }

  # Secrets Manager (for API keys in processing jobs)
  statement {
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = [
      aws_secretsmanager_secret.bitoguard_api_key.arn
    ]
  }

  # SageMaker Model Registry (for model registration)
  statement {
    actions = [
      "sagemaker:CreateModelPackage",
      "sagemaker:DescribeModelPackage",
      "sagemaker:UpdateModelPackage"
    ]
    resources = [
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:model-package-group/${local.name_prefix}-*",
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:model-package/${local.name_prefix}-*/*"
    ]
  }

  # SageMaker Endpoints (for model deployment)
  statement {
    actions = [
      "sagemaker:CreateModel",
      "sagemaker:CreateEndpointConfig",
      "sagemaker:CreateEndpoint",
      "sagemaker:DescribeEndpoint",
      "sagemaker:DescribeEndpointConfig",
      "sagemaker:DescribeModel",
      "sagemaker:InvokeEndpoint"
    ]
    resources = [
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:model/${local.name_prefix}-*",
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:endpoint-config/${local.name_prefix}-*",
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:endpoint/${local.name_prefix}-*"
    ]
  }

  # EC2 for VPC configuration (if endpoints deployed in VPC)
  statement {
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:CreateNetworkInterfacePermission",
      "ec2:DeleteNetworkInterface",
      "ec2:DeleteNetworkInterfacePermission",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeVpcs",
      "ec2:DescribeDhcpOptions",
      "ec2:DescribeSubnets",
      "ec2:DescribeSecurityGroups"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sagemaker_execution" {
  name   = "${local.name_prefix}-sagemaker-execution-policy"
  role   = aws_iam_role.sagemaker_execution.id
  policy = data.aws_iam_policy_document.sagemaker_execution.json
}

# Lambda Execution Role for Drift Detector
resource "aws_iam_role" "drift_detector_lambda" {
  name = "${local.name_prefix}-drift-detector-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-drift-detector-lambda-role"
  })
}

data "aws_iam_policy_document" "drift_detector_lambda" {
  # S3 access for feature snapshots and drift reports
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*"
    ]
  }

  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name_prefix}-drift-detector:*"
    ]
  }

  # CloudWatch Metrics
  statement {
    actions = [
      "cloudwatch:PutMetricData"
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["BitoGuard/MLPipeline"]
    }
  }

  # SNS for drift alerts
  statement {
    actions = [
      "sns:Publish"
    ]
    resources = [
      aws_sns_topic.drift_alerts.arn
    ]
  }

  # SSM Parameter Store
  statement {
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters"
    ]
    resources = [
      "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/bitoguard/ml-pipeline/drift/*"
    ]
  }
}

resource "aws_iam_role_policy" "drift_detector_lambda" {
  name   = "${local.name_prefix}-drift-detector-lambda-policy"
  role   = aws_iam_role.drift_detector_lambda.id
  policy = data.aws_iam_policy_document.drift_detector_lambda.json
}

# Lambda Execution Role for Config Validator
resource "aws_iam_role" "config_validator_lambda" {
  name = "${local.name_prefix}-config-validator-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-config-validator-lambda-role"
  })
}

data "aws_iam_policy_document" "config_validator_lambda" {
  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name_prefix}-config-validator:*"
    ]
  }

  # SSM Parameter Store - read all ML pipeline parameters
  statement {
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath"
    ]
    resources = [
      "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/bitoguard/ml-pipeline/*"
    ]
  }

  # S3 - check bucket existence
  statement {
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = [
      aws_s3_bucket.artifacts.arn
    ]
  }
}

resource "aws_iam_role_policy" "config_validator_lambda" {
  name   = "${local.name_prefix}-config-validator-lambda-policy"
  role   = aws_iam_role.config_validator_lambda.id
  policy = data.aws_iam_policy_document.config_validator_lambda.json
}

# Lambda Execution Role for Manual Trigger
resource "aws_iam_role" "manual_trigger_lambda" {
  name = "${local.name_prefix}-manual-trigger-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-manual-trigger-lambda-role"
  })
}

data "aws_iam_policy_document" "manual_trigger_lambda" {
  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name_prefix}-manual-trigger:*"
    ]
  }

  # Step Functions - start execution
  statement {
    actions = [
      "states:StartExecution"
    ]
    resources = [
      "arn:aws:states:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.name_prefix}-ml-pipeline"
    ]
  }
}

resource "aws_iam_role_policy" "manual_trigger_lambda" {
  name   = "${local.name_prefix}-manual-trigger-lambda-policy"
  role   = aws_iam_role.manual_trigger_lambda.id
  policy = data.aws_iam_policy_document.manual_trigger_lambda.json
}

# EventBridge Role for Step Functions
resource "aws_iam_role" "eventbridge_stepfunctions" {
  name = "${local.name_prefix}-eventbridge-stepfunctions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-eventbridge-stepfunctions-role"
  })
}

data "aws_iam_policy_document" "eventbridge_stepfunctions" {
  statement {
    actions = [
      "states:StartExecution"
    ]
    resources = [
      "arn:aws:states:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.name_prefix}-ml-pipeline"
    ]
  }
}

resource "aws_iam_role_policy" "eventbridge_stepfunctions" {
  name   = "${local.name_prefix}-eventbridge-stepfunctions-policy"
  role   = aws_iam_role.eventbridge_stepfunctions.id
  policy = data.aws_iam_policy_document.eventbridge_stepfunctions.json
}

# Step Functions Execution Role
resource "aws_iam_role" "stepfunctions_execution" {
  name = "${local.name_prefix}-stepfunctions-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-stepfunctions-execution-role"
  })
}

data "aws_iam_policy_document" "stepfunctions_execution" {
  # ECS task execution
  statement {
    actions = [
      "ecs:RunTask"
    ]
    resources = [
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name_prefix}-sync-task:*",
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name_prefix}-features-task:*",
      "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name_prefix}-scoring-task:*"
    ]
  }

  statement {
    actions = [
      "ecs:StopTask",
      "ecs:DescribeTasks"
    ]
    resources = ["*"]
  }

  statement {
    actions = [
      "iam:PassRole"
    ]
    resources = [
      aws_iam_role.ecs_task_execution.arn,
      aws_iam_role.ml_pipeline_task.arn
    ]
  }

  # SageMaker training jobs
  statement {
    actions = [
      "sagemaker:CreateTrainingJob",
      "sagemaker:DescribeTrainingJob",
      "sagemaker:StopTrainingJob"
    ]
    resources = [
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:training-job/${local.name_prefix}-*"
    ]
  }

  # SageMaker processing jobs
  statement {
    actions = [
      "sagemaker:CreateProcessingJob",
      "sagemaker:DescribeProcessingJob",
      "sagemaker:StopProcessingJob"
    ]
    resources = [
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:processing-job/${local.name_prefix}-*"
    ]
  }

  # SageMaker hyperparameter tuning jobs
  statement {
    actions = [
      "sagemaker:CreateHyperParameterTuningJob",
      "sagemaker:DescribeHyperParameterTuningJob",
      "sagemaker:StopHyperParameterTuningJob",
      "sagemaker:ListTrainingJobsForHyperParameterTuningJob"
    ]
    resources = [
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:hyper-parameter-tuning-job/${local.name_prefix}-*"
    ]
  }

  # SageMaker batch transform jobs
  statement {
    actions = [
      "sagemaker:CreateTransformJob",
      "sagemaker:DescribeTransformJob",
      "sagemaker:StopTransformJob"
    ]
    resources = [
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:transform-job/${local.name_prefix}-*"
    ]
  }

  statement {
    actions = [
      "iam:PassRole"
    ]
    resources = [
      aws_iam_role.sagemaker_execution.arn
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["sagemaker.amazonaws.com"]
    }
  }

  # Lambda invocation
  statement {
    actions = [
      "lambda:InvokeFunction"
    ]
    resources = [
      "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-drift-detector",
      "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-config-validator",
      "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-tuning-analyzer",
      "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-model-registry"
    ]
  }

  # CloudWatch metrics
  statement {
    actions = [
      "cloudwatch:PutMetricData"
    ]
    resources = ["*"]
  }

  # SNS notifications
  statement {
    actions = [
      "sns:Publish"
    ]
    resources = [
      aws_sns_topic.ml_pipeline_notifications.arn,
      aws_sns_topic.critical_errors.arn
    ]
  }

  # CloudWatch Events (for scheduling)
  statement {
    actions = [
      "events:PutTargets",
      "events:PutRule",
      "events:DescribeRule"
    ]
    resources = [
      "arn:aws:events:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForECSTaskRule",
      "arn:aws:events:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForSageMakerTrainingJobsRule",
      "arn:aws:events:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForSageMakerProcessingJobsRule",
      "arn:aws:events:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForSageMakerTransformJobsRule"
    ]
  }
}

resource "aws_iam_role_policy" "stepfunctions_execution" {
  name   = "${local.name_prefix}-stepfunctions-execution-policy"
  role   = aws_iam_role.stepfunctions_execution.id
  policy = data.aws_iam_policy_document.stepfunctions_execution.json
}

# Outputs
output "ml_pipeline_task_role_arn" {
  description = "ARN of ML pipeline task role"
  value       = aws_iam_role.ml_pipeline_task.arn
}

output "sagemaker_execution_role_arn" {
  description = "ARN of SageMaker execution role"
  value       = aws_iam_role.sagemaker_execution.arn
}

output "stepfunctions_execution_role_arn" {
  description = "ARN of Step Functions execution role"
  value       = aws_iam_role.stepfunctions_execution.arn
}

# Lambda Execution Role for Tuning Analyzer
resource "aws_iam_role" "tuning_analyzer_lambda" {
  name = "${local.name_prefix}-tuning-analyzer-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-tuning-analyzer-lambda-role"
  })
}

data "aws_iam_policy_document" "tuning_analyzer_lambda" {
  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name_prefix}-tuning-analyzer:*"
    ]
  }

  # SageMaker read access for tuning jobs
  statement {
    actions = [
      "sagemaker:DescribeHyperParameterTuningJob",
      "sagemaker:DescribeTrainingJob",
      "sagemaker:ListTrainingJobsForHyperParameterTuningJob"
    ]
    resources = [
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:hyper-parameter-tuning-job/bitoguard-*",
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:training-job/bitoguard-*"
    ]
  }

  # S3 access for saving tuning results
  statement {
    actions = [
      "s3:PutObject",
      "s3:GetObject"
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/tuning-analysis/*"
    ]
  }
}

resource "aws_iam_role_policy" "tuning_analyzer_lambda" {
  name   = "${local.name_prefix}-tuning-analyzer-lambda-policy"
  role   = aws_iam_role.tuning_analyzer_lambda.id
  policy = data.aws_iam_policy_document.tuning_analyzer_lambda.json
}


# Lambda Execution Role for Model Registry
resource "aws_iam_role" "model_registry_lambda" {
  name = "${local.name_prefix}-model-registry-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-model-registry-lambda-role"
  })
}

data "aws_iam_policy_document" "model_registry_lambda" {
  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name_prefix}-model-registry:*"
    ]
  }

  # SageMaker model registry access
  statement {
    actions = [
      "sagemaker:CreateModelPackage",
      "sagemaker:DescribeModelPackage",
      "sagemaker:UpdateModelPackage",
      "sagemaker:ListModelPackages",
      "sagemaker:DescribeTrainingJob"
    ]
    resources = [
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:model-package-group/${local.name_prefix}-*",
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:model-package/${local.name_prefix}-*/*",
      "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:training-job/bitoguard-*"
    ]
  }

  # S3 access for model artifacts and registration records
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/models/*",
      "${aws_s3_bucket.artifacts.arn}/model-registry/*"
    ]
  }
}

resource "aws_iam_role_policy" "model_registry_lambda" {
  name   = "${local.name_prefix}-model-registry-lambda-policy"
  role   = aws_iam_role.model_registry_lambda.id
  policy = data.aws_iam_policy_document.model_registry_lambda.json
}
