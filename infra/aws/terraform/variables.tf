variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "backend_cpu" {
  description = "CPU units for backend task"
  type        = number
  default     = 1024
}

variable "backend_memory" {
  description = "Memory for backend task (MB)"
  type        = number
  default     = 2048
}

variable "frontend_cpu" {
  description = "CPU units for frontend task"
  type        = number
  default     = 512
}

variable "frontend_memory" {
  description = "Memory for frontend task (MB)"
  type        = number
  default     = 1024
}

variable "backend_desired_count" {
  description = "Desired number of backend tasks"
  type        = number
  default     = 2
}

variable "frontend_desired_count" {
  description = "Desired number of frontend tasks"
  type        = number
  default     = 2
}

variable "bitoguard_source_url" {
  description = "BitoPro source API URL"
  type        = string
  default     = "https://aws-event-api.bitopro.com"
}

variable "domain_name" {
  description = "Domain name for the application (optional)"
  type        = string
  default     = ""
}

# ML Pipeline Variables
variable "ml_notification_email" {
  description = "Email address for ML pipeline notifications"
  type        = string
  default     = ""
}

variable "bitopro_api_url" {
  description = "BitoPro API endpoint URL"
  type        = string
  default     = "https://aws-event-api.bitopro.com"
}

variable "ml_daily_schedule" {
  description = "Cron expression for daily full pipeline run"
  type        = string
  default     = "cron(0 2 * * ? *)" # 2 AM UTC daily
}

variable "ml_incremental_schedule" {
  description = "Cron expression for incremental refresh"
  type        = string
  default     = "cron(0 8,12,16,20 * * ? *)" # Every 4 hours, 8 AM - 8 PM UTC
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "bitoguard"
}

variable "github_repo_url" {
  description = "GitHub repository URL for Amplify (e.g. https://github.com/org/repo)"
  type        = string
  default     = ""
}

variable "github_access_token" {
  description = "GitHub personal access token for Amplify repo connection"
  type        = string
  sensitive   = true
  default     = ""
}
