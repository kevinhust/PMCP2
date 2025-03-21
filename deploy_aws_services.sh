#!/bin/bash

# =============== Configuration Section ===============
# AWS Region Configuration
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Resource Name Configuration
# Add environment identifier
ENVIRONMENT="dev"
PROJECT_NAME="stock-analysis"

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

# SageMaker Configuration
SAGEMAKER_ENDPOINT="tsla-stock-predictor"
SAGEMAKER_CONFIG_NAME="${SAGEMAKER_ENDPOINT}-config"
SAGEMAKER_MODEL_NAME="tsla-stock-model"

# =============== Helper Functions ===============
function check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "$1 is not installed. Please install it first."
        exit 1
    fi
}

# =============== Execution Section ===============
# Check for required tools
check_command "aws"

# Create IAM role with expanded permissions
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

# Attach necessary IAM policies
echo "Attaching IAM policies..."
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole || { echo "Basic execution policy attachment failed"; exit 1; }

aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonKinesisFullAccess || { echo "Kinesis policy attachment failed"; exit 1; }

aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess || { echo "DynamoDB policy attachment failed"; exit 1; }

aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess || { echo "SageMaker policy attachment failed"; exit 1; }

# Wait for IAM role to be ready
echo "Waiting for IAM role to be ready..."
aws iam wait role-exists --role-name "$ROLE_NAME" || { echo "IAM role not ready"; exit 1; }

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
# Check if stream exists
if aws kinesis describe-stream --stream-name "$STREAM_NAME" --region "$REGION" 2>/dev/null; then
    echo "Stream already exists. Deleting it first..."
    aws kinesis delete-stream --stream-name "$STREAM_NAME" --region "$REGION"
    # Wait for stream to be deleted
    aws kinesis wait stream-not-exists --stream-name "$STREAM_NAME" --region "$REGION"
fi

# Create new stream
aws kinesis create-stream \
    --stream-name "$STREAM_NAME" \
    --shard-count "$STREAM_SHARD_COUNT" \
    --region "$REGION" || { echo "Kinesis creation failed"; exit 1; }

# Wait for stream to be ready
echo "Waiting for Kinesis stream to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    STREAM_STATUS=$(aws kinesis describe-stream \
        --stream-name "$STREAM_NAME" \
        --region "$REGION" \
        --query 'StreamDescription.StreamStatus' \
        --output text 2>/dev/null || echo "CREATING")
    
    if [ "$STREAM_STATUS" = "ACTIVE" ]; then
        echo "Kinesis stream '$STREAM_NAME' is now active!"
        break
    elif [ "$STREAM_STATUS" = "CREATING" ]; then
        echo "Stream is still creating... (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"
        sleep 10
        RETRY_COUNT=$((RETRY_COUNT + 1))
    else
        echo "Unexpected stream status: $STREAM_STATUS"
        exit 1
    fi
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Timeout waiting for Kinesis stream to become active"
    exit 1
fi

# Create DynamoDB table with on-demand capacity
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

# Wait for DynamoDB table to be active with timeout
echo "Waiting for DynamoDB table to be active..."
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    TABLE_STATUS=$(aws dynamodb describe-table \
        --table-name "$TABLE_NAME" \
        --region "$REGION" \
        --query 'Table.TableStatus' \
        --output text 2>/dev/null || echo "CREATING")
    
    if [ "$TABLE_STATUS" = "ACTIVE" ]; then
        echo "DynamoDB table '$TABLE_NAME' is now active!"
        break
    elif [ "$TABLE_STATUS" = "CREATING" ]; then
        echo "Table is still creating... (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"
        sleep 10
        RETRY_COUNT=$((RETRY_COUNT + 1))
    else
        echo "Unexpected table status: $TABLE_STATUS"
        exit 1
    fi
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Timeout waiting for DynamoDB table to become active"
    exit 1
fi

echo "AWS infrastructure deployment completed successfully!"
