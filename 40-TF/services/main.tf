provider "aws" {
  region = var.aws_region
}

# Data Sources
data "aws_caller_identity" "current" {}

locals {
  common_tags = {
    Project     = "stock-analysis"
    Environment = "production"
    Terraform   = "true"
  }
}

# DynamoDB Table
resource "aws_dynamodb_table" "stock_table" {
  name           = "stock-indicators"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "symbol"
  range_key      = "timestamp"

  attribute {
    name = "symbol"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = local.common_tags
}

# Kinesis Stream
resource "aws_kinesis_stream" "stock_stream" {
  name             = "stock-stream"
  shard_count      = 2
  retention_period = 24

  tags = local.common_tags
}

# IAM Roles and Policies
resource "aws_iam_role" "lambda_exec" {
  name = "lambda_exec_role"

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
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "kinesis_policy" {
  name = "kinesis_access_policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:PutRecord",
          "kinesis:PutRecords",
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:ListStreams"
        ]
        Resource = aws_kinesis_stream.stock_stream.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "dynamodb_policy" {
  name = "dynamodb_access_policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
          "dynamodb:DescribeStream",
          "dynamodb:ListStreams"
        ]
        Resource = [
          aws_dynamodb_table.stock_table.arn,
          "${aws_dynamodb_table.stock_table.arn}/stream/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "s3_policy" {
  name = "s3_access_policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::kevinw-p2/*",
          "arn:aws:s3:::kevinw-p2"
        ]
      }
    ]
  })
}

# Lambda Functions
resource "aws_lambda_function" "push_to_kinesis" {
  function_name = "push-to-kinesis"
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  image_uri     = "039444453392.dkr.ecr.us-east-1.amazonaws.com/pmc/push_to_kinesis:latest"
  timeout       = 60
  memory_size   = 1024

  environment {
    variables = {
      KINESIS_STREAM_NAME = aws_kinesis_stream.stock_stream.name
      STOCK_SYMBOLS      = "AAPL,MSFT,GOOGL,AMZN,TSLA,FB,NFLX,NVDA,JPM,V"
    }
  }

  tags = local.common_tags
}

resource "aws_lambda_function" "process_stock_data" {
  function_name = "process-stock-data"
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  image_uri     = "039444453392.dkr.ecr.us-east-1.amazonaws.com/pmc/process_stock_data:latest"
  timeout       = 60
  memory_size   = 1024

  environment {
    variables = {
      KINESIS_STREAM_NAME = aws_kinesis_stream.stock_stream.name
      DYNAMO_TABLE        = aws_dynamodb_table.stock_table.name
    }
  }

  tags = local.common_tags
}

resource "aws_lambda_function" "export_dynamodb_to_s3" {
  function_name = "export-dynamodb-to-s3"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.9"
  s3_bucket     = "kevinw-p2"
  s3_key        = "lambda/export_dynamodb_to_s3.zip"
  timeout       = 60
  memory_size   = 1024

  environment {
    variables = {
      DYNAMO_TABLE = aws_dynamodb_table.stock_table.name
      S3_BUCKET    = "kevinw-p2"
      S3_PREFIX    = "stock-data"
    }
  }

  tags = local.common_tags
}

# Event Triggers
resource "aws_cloudwatch_event_rule" "push_to_kinesis_trigger" {
  name                = "push-to-kinesis-trigger"
  description         = "Trigger push-to-kinesis every minute"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "push_to_kinesis_target" {
  rule      = aws_cloudwatch_event_rule.push_to_kinesis_trigger.name
  arn       = aws_lambda_function.push_to_kinesis.arn
  target_id = "PushToKinesis"
}

resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.push_to_kinesis.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.push_to_kinesis_trigger.arn
}

# Event Source Mappings
resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn  = aws_kinesis_stream.stock_stream.arn
  function_name     = aws_lambda_function.process_stock_data.arn
  starting_position = "LATEST"
  batch_size        = 100
}

resource "aws_lambda_event_source_mapping" "dynamodb_trigger" {
  event_source_arn  = aws_dynamodb_table.stock_table.stream_arn
  function_name     = aws_lambda_function.export_dynamodb_to_s3.arn
  starting_position = "LATEST"
  batch_size        = 100
}

# SNS Topic and Subscription
resource "aws_sns_topic" "alerts" {
  name = "stock-analysis-alerts"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# CloudWatch Alarms
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = {
    push_to_kinesis      = aws_lambda_function.push_to_kinesis.function_name
    process_stock_data   = aws_lambda_function.process_stock_data.function_name
    export_dynamodb_to_s3 = aws_lambda_function.export_dynamodb_to_s3.function_name
  }

  alarm_name          = "${each.key}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "300"
  statistic          = "Sum"
  threshold          = "0"
  alarm_description  = "Monitor for ${each.key} Lambda function errors"
  alarm_actions      = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = each.value
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  for_each = {
    push_to_kinesis      = aws_lambda_function.push_to_kinesis.function_name
    process_stock_data   = aws_lambda_function.process_stock_data.function_name
    export_dynamodb_to_s3 = aws_lambda_function.export_dynamodb_to_s3.function_name
  }

  alarm_name          = "${each.key}-duration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = "300"
  statistic          = "Average"
  threshold          = "45000"
  alarm_description  = "Monitor for ${each.key} Lambda function duration"
  alarm_actions      = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = each.value
  }
}
