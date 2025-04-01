# main.tf

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
  name           = var.dynamodb_table_name
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
  name             = var.kinesis_stream_name
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
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.stock_table.arn
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
          "arn:aws:s3:::${var.s3_bucket_name}/*",
          "arn:aws:s3:::${var.s3_bucket_name}"
        ]
      }
    ]
  })
}

# Lambda Layer for push_to_kinesis
resource "aws_lambda_layer_version" "kinesis_layer" {
  layer_name          = "kinesis-layer"
  description         = "Layer containing Kinesis dependencies"
  s3_bucket          = var.s3_bucket_name
  s3_key             = "lambda/kinesis_layer.zip"
  compatible_runtimes = ["python3.9"]
}

# Lambda Functions
resource "aws_lambda_function" "push_to_kinesis" {
  function_name = "push-to-kinesis"
  role          = aws_iam_role.lambda_exec.arn
  s3_bucket     = var.s3_bucket_name
  s3_key        = "lambda/push_to_kinesis.zip"
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.9"
  timeout       = 60
  memory_size   = 1024

  # Add the layer to the function
  layers = [aws_lambda_layer_version.kinesis_layer.arn]

  environment {
    variables = {
      KINESIS_STREAM_NAME = aws_kinesis_stream.stock_stream.name
      STOCK_SYMBOLS      = join(",", var.stock_symbols)
      ALPHA_VANTAGE_API_KEY = var.alpha_vantage_api_key
    }
  }

  tags = local.common_tags
}

resource "aws_lambda_function" "process_stock_data" {
  function_name = "process-stock-data"
  role          = aws_iam_role.lambda_exec.arn
  s3_bucket     = var.s3_bucket_name
  s3_key        = "lambda/process_stock_data.zip"
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.9"
  timeout       = 60
  memory_size   = 1024

  # Add AWS SDK Pandas Layer
  layers = ["arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python39:28"]

  environment {
    variables = {
      KINESIS_STREAM_NAME = aws_kinesis_stream.stock_stream.name
      DYNAMO_TABLE        = aws_dynamodb_table.stock_table.name
      STOCK_SYMBOLS      = join(",", var.stock_symbols)
    }
  }

  tags = local.common_tags
}

# Add Kinesis trigger for process-stock-data Lambda
resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn  = aws_kinesis_stream.stock_stream.arn
  function_name     = aws_lambda_function.process_stock_data.arn
  starting_position = "LATEST"
  batch_size        = 100
  enabled           = true
}

resource "aws_lambda_function" "export_dynamodb_to_s3" {
  function_name = "export-dynamodb-to-s3"
  role          = aws_iam_role.lambda_exec.arn
  s3_bucket     = var.s3_bucket_name
  s3_key        = "lambda/export_dynamodb_to_s3.zip"
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.9"
  timeout       = 60
  memory_size   = 1024

  # Add AWS SDK Pandas Layer
  layers = ["arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python39:28"]

  environment {
    variables = {
      DYNAMO_TABLE = aws_dynamodb_table.stock_table.name
      S3_BUCKET    = var.s3_bucket_name
      S3_KEY       = "stock-data/data.csv"
      S3_PREFIX    = "stock-data/"
    }
  }

  tags = local.common_tags
}

# Event Triggers
# Start rule - Every weekday at 9:00 AM ET (Toronto time)
resource "aws_cloudwatch_event_rule" "start_trading" {
  name                = "start-trading-day"
  description         = "Start trading day at 9:00 AM ET (Toronto time)"
  schedule_expression = "cron(0 13 ? * MON-FRI *)"  # UTC 13:00 = ET 9:00
  is_enabled         = true
}

resource "aws_cloudwatch_event_target" "start_trading_target" {
  rule      = aws_cloudwatch_event_rule.start_trading.name
  arn       = aws_lambda_function.push_to_kinesis.arn
  target_id = "StartTradingDay"

  # Add input parameter to identify the event type
  input = jsonencode({
    action = "START_TRADING"
    message = "Start daily trading operations"
  })
}

resource "aws_lambda_permission" "allow_cloudwatch_start" {
  statement_id  = "AllowExecutionFromCloudWatchStart"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.push_to_kinesis.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.start_trading.arn
}

# Stop rule - Every weekday at 7:00 PM ET (Toronto time)
resource "aws_cloudwatch_event_rule" "stop_trading" {
  name                = "stop-trading-day"
  description         = "Stop trading day at 7:00 PM ET (Toronto time)"
  schedule_expression = "cron(0 23 ? * MON-FRI *)"  # UTC 23:00 = ET 19:00
  is_enabled         = true
}

resource "aws_cloudwatch_event_target" "stop_trading_target" {
  rule      = aws_cloudwatch_event_rule.stop_trading.name
  arn       = aws_lambda_function.push_to_kinesis.arn
  target_id = "StopTradingDay"

  # Add input parameter to identify the event type
  input = jsonencode({
    action = "STOP_TRADING"
    message = "Stop daily trading operations"
  })
}

resource "aws_lambda_permission" "allow_cloudwatch_stop" {
  statement_id  = "AllowExecutionFromCloudWatchStop"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.push_to_kinesis.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.stop_trading.arn
}

# CloudWatch Event Rule for export_dynamodb_to_s3
resource "aws_cloudwatch_event_rule" "export_dynamodb_to_s3_trigger" {
  name                = "export-dynamodb-to-s3-trigger"
  description         = "Trigger export-dynamodb-to-s3 every minute"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "export_dynamodb_to_s3_target" {
  rule      = aws_cloudwatch_event_rule.export_dynamodb_to_s3_trigger.name
  arn       = aws_lambda_function.export_dynamodb_to_s3.arn
  target_id = "ExportDynamoDBToS3"
}

resource "aws_lambda_permission" "allow_cloudwatch_export" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.export_dynamodb_to_s3.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.export_dynamodb_to_s3_trigger.arn
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
