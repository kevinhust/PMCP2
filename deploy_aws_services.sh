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
BUCKET_VERSIONING="Enabled"

# Kinesis Configuration
STREAM_NAME="stock-stream"
STREAM_SHARD_COUNT=1
RETENTION_HOURS=24

# DynamoDB Configuration
TABLE_NAME="stock-table"
TABLE_HASH_KEY="stock_symbol"
TABLE_RANGE_KEY="timestamp"

# Lambda Configuration
LAMBDA_FUNCTION_NAME="${PROJECT_NAME}-processor"
LAMBDA_MEMORY=256
LAMBDA_TIMEOUT=300
LAMBDA_RUNTIME="python3.9"

# IAM Configuration
ROLE_NAME="${PROJECT_NAME}-role"
ROLE_DESCRIPTION="Role for Stock Analysis System"

# Tags
COMMON_TAGS="{
    \"Project\":\"${PROJECT_NAME}\",
    \"Environment\":\"${ENVIRONMENT}\",
    \"ManagedBy\":\"terraform\"
}"

# =============== Helper Functions ===============
function check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "$1 is not installed. Please install it first."
        exit 1
    fi
}

function wait_for_resource() {
    echo "Waiting for $1..."
    sleep 10
}

# =============== Execution Section ===============
# Check for required tools
check_command "aws"
check_command "jq"

# Create S3 bucket with encryption and versioning
echo "Creating S3 bucket '$BUCKET_NAME'..."
if aws s3api create-bucket \
    --bucket "$BUCKET_NAME" \
    --region "$REGION" \
    ${REGION != "us-east-1" ? "--create-bucket-configuration LocationConstraint=$REGION" : ""}; then
    
    # Enable versioning
    aws s3api put-bucket-versioning \
        --bucket "$BUCKET_NAME" \
        --versioning-configuration Status=$BUCKET_VERSIONING

    # Enable encryption
    aws s3api put-bucket-encryption \
        --bucket "$BUCKET_NAME" \
        --server-side-encryption-configuration '{
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256"
                    }
                }
            ]
        }'

    # Add bucket policy
    aws s3api put-bucket-policy \
        --bucket "$BUCKET_NAME" \
        --policy '{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyUnencryptedObjectUploads",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "s3:PutObject",
                    "Resource": "arn:aws:s3:::'$BUCKET_NAME'/*",
                    "Condition": {
                        "StringNotEquals": {
                            "s3:x-amz-server-side-encryption": "AES256"
                        }
                    }
                }
            ]
        }'
else
    echo "S3 bucket creation failed"
    exit 1
fi

# Create Kinesis stream with encryption
echo "Creating Kinesis stream '$STREAM_NAME'..."
aws kinesis create-stream \
    --stream-name "$STREAM_NAME" \
    --shard-count "$STREAM_SHARD_COUNT" \
    --retention-period-hours "$RETENTION_HOURS" \
    --region "$REGION" \
    --encryption-type KMS \
    --key-id alias/aws/kinesis || { echo "Kinesis creation failed"; exit 1; }

wait_for_resource "Kinesis stream"

# Create DynamoDB table with encryption and backup
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
    --sse-specification Enabled=true \
    --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES \
    --tags "$COMMON_TAGS" \
    --region "$REGION" || { echo "DynamoDB table creation failed"; exit 1; }

wait_for_resource "DynamoDB table"

# Enable point-in-time recovery
aws dynamodb update-continuous-backups \
    --table-name "$TABLE_NAME" \
    --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true

# Create IAM role with least privilege
echo "Creating IAM role '$ROLE_NAME'..."
aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": [
                        "lambda.amazonaws.com",
                        "sagemaker.amazonaws.com"
                    ]
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }' || { echo "IAM role creation failed"; exit 1; }

# Create custom policy for least privilege
aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "${ROLE_NAME}-policy" \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "kinesis:GetRecords",
                    "kinesis:GetShardIterator",
                    "kinesis:DescribeStream",
                    "kinesis:ListShards"
                ],
                "Resource": "arn:aws:kinesis:'$REGION':'$ACCOUNT_ID':stream/'$STREAM_NAME'"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:Query"
                ],
                "Resource": "arn:aws:dynamodb:'$REGION':'$ACCOUNT_ID':table/'$TABLE_NAME'"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "sagemaker:InvokeEndpoint"
                ],
                "Resource": "arn:aws:sagemaker:'$REGION':'$ACCOUNT_ID':endpoint/*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:'$REGION':'$ACCOUNT_ID':*"
            }
        ]
    }'

wait_for_resource "IAM role"

echo "AWS services deployment completed successfully!"
echo "Next steps:"
echo "1. Deploy Lambda function with the following environment variables:"
echo "   - DYNAMODB_TABLE=$TABLE_NAME"
echo "   - SAGEMAKER_ENDPOINT=<your-endpoint-name>"
echo "2. Configure Kinesis trigger for Lambda"
echo "3. Deploy SageMaker endpoint"
echo "4. Test the pipeline"