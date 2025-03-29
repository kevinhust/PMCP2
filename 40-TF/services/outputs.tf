output "kinesis_stream_name" {
  value = aws_kinesis_stream.stock_stream.name
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.stock_table.name
}

output "dynamodb_stream_arn" {
  value = aws_dynamodb_table.stock_table.stream_arn
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
