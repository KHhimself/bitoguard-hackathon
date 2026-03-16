# AWS Amplify Frontend (Next.js SSR)
# Ref: https://docs.aws.amazon.com/amplify/latest/userguide/server-side-rendering-amplify.html
# Ref: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/amplify_app

resource "aws_amplify_app" "frontend" {
  count        = var.github_repo_url != "" ? 1 : 0
  name         = "${local.name_prefix}-frontend"
  repository   = var.github_repo_url
  access_token = var.github_access_token

  # WEB_COMPUTE required for Next.js SSR and API routes
  platform = "WEB_COMPUTE"

  build_spec = <<-EOT
    version: 1
    frontend:
      phases:
        preBuild:
          commands:
            - cd bitoguard_frontend
            - npm ci
        build:
          commands:
            - cd bitoguard_frontend
            - npm run build
      artifacts:
        baseDirectory: bitoguard_frontend/.next
        files:
          - '**/*'
      cache:
        paths:
          - bitoguard_frontend/node_modules/**/*
  EOT

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-frontend"
  })
}

resource "aws_amplify_branch" "main" {
  count       = var.github_repo_url != "" ? 1 : 0
  app_id      = aws_amplify_app.frontend[0].id
  branch_name = "main"
  framework   = "Next.js - SSR"
  stage       = "PRODUCTION"

  environment_variables = {
    # Backend API base — proxied through Next.js API routes
    # Set to the internal ALB DNS (not public) since Amplify SSR runs server-side
    BITOGUARD_INTERNAL_API_BASE = "http://${aws_lb.main.dns_name}"
    NODE_ENV                    = "production"
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-frontend-main"
  })
}

output "amplify_app_url" {
  description = "Amplify app default domain"
  value       = var.github_repo_url != "" ? "https://main.${aws_amplify_app.frontend[0].default_domain}" : "N/A (no GitHub repo configured)"
}

output "amplify_app_id" {
  description = "Amplify app ID (for manual deploys)"
  value       = var.github_repo_url != "" ? aws_amplify_app.frontend[0].id : "N/A"
}
