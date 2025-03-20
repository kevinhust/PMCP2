#!/bin/bash

# =============== Configuration Section ===============
# AWS Region Configuration
REGION="us-east-1"

# Resource Name Configuration
# S3 Configuration
BUCKET_NAME="kevinw-p2"

# Kinesis Configuration
STREAM_NAME="stock-stream"
STREAM_SHARD_COUNT=1

# DynamoDB Configuration
TABLE_NAME="stock-table"
TABLE_HASH_KEY="stock_symbol"
TABLE_RANGE_KEY="timestamp"

# IAM Configuration
ROLE_NAME="StockAnalysisRole"
ROLE_DESCRIPTION="Role for Stock Analysis System"

# =============== Execution Section ===============
# Check for AWS CLI
if ! command -v aws &> /dev/null; then
    echo "AWS CLI is not installed. Please install it first."
    exit 1
fi

# Create S3 bucket
echo "Creating S3 bucket '$BUCKET_NAME'..."
if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket \
        --bucket "$BUCKET_NAME" \
        --region "$REGION" || { echo "S3 creation failed"; exit 1; }
else
    aws s3api create-bucket \
        --bucket "$BUCKET_NAME" \
        --region "$REGION" \
        --create-bucket-configuration LocationConstraint="$REGION" || { echo "S3 creation failed"; exit 1; }
fi

# Create Kinesis stream
echo "Creating Kinesis stream '$STREAM_NAME'..."
aws kinesis create-stream \
    --stream-name "$STREAM_NAME" \
    --shard-count "$STREAM_SHARD_COUNT" \
    --region "$REGION" || { echo "Kinesis creation failed"; exit 1; }
aws kinesis wait stream-exists --stream-name "$STREAM_NAME" --region "$REGION"

# Create DynamoDB table
echo "Creating DynamoDB table '$TABLE_NAME'..."
aws dynamodb create-table \
    --table-name "$TABLE_NAME" \
    --attribute-definitions \
        AttributeName="$TABLE_HASH_KEY",AttributeType=S \
        AttributeName="$TABLE_RANGE_KEY",AttributeType=N \
    --key-schema \
        AttributeName="$TABLE_HASH_KEY",KeyType=HASH \
        AttributeName="$TABLE_RANGE_KEY",KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" || { echo "DynamoDB table creation failed"; exit 1; }
aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"

# Create IAM role
echo "Creating IAM role '$ROLE_NAME'..."
aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": ["lambda.amazonaws.com", "sagemaker.amazonaws.com"]
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }' || { echo "IAM role creation failed"; exit 1; }

# Attach IAM policies
echo "Attaching IAM policies..."
for policy in \
    "service-role/AWSLambdaBasicExecutionRole" \
    "AmazonKinesisFullAccess" \
    "AmazonDynamoDBFullAccess" \
    "AmazonSageMakerFullAccess" \
    "AmazonS3FullAccess"; do
    aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/$policy" || { echo "Policy $policy attachment failed"; exit 1; }
done
aws iam wait role-exists --role-name "$ROLE_NAME"

echo "AWS services deployment completed! Please manually create Lambda layer, trigger, and SageMaker endpoint."