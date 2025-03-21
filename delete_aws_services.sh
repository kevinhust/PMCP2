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
S3_LAYER_KEY="ta_lib_layer.zip"

# Kinesis Configuration
STREAM_NAME="stock-stream"

# DynamoDB Configuration
TABLE_NAME="stock-table"

# IAM Configuration
ROLE_NAME="${PROJECT_NAME}-role"

# Lambda Configuration
LAMBDA_FUNCTION_NAME="${PROJECT_NAME}-processor"

# Lambda Layer Configuration
LAYER_NAME="ta-lib-layer"

# SageMaker Configuration
SAGEMAKER_ENDPOINT="tsla-stock-predictor"
SAGEMAKER_CONFIG_NAME="${SAGEMAKER_ENDPOINT}-config"

# =============== Helper Functions ===============
function check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "$1 is not installed. Please install it first."
        exit 1
    fi
}

function handle_error() {
    echo "Warning: $1"
    return 1
}

# =============== Execution Section ===============
# Check for required tools
check_command "aws"

# Delete SageMaker endpoint
echo "Deleting SageMaker endpoint '$SAGEMAKER_ENDPOINT'..."
aws sagemaker delete-endpoint \
    --endpoint-name "$SAGEMAKER_ENDPOINT" \
    --region "$REGION" || handle_error "SageMaker endpoint deletion failed"

# Delete SageMaker endpoint config
echo "Deleting SageMaker endpoint config '$SAGEMAKER_CONFIG_NAME'..."
aws sagemaker delete-endpoint-config \
    --endpoint-config-name "$SAGEMAKER_CONFIG_NAME" \
    --region "$REGION" || handle_error "SageMaker endpoint config deletion failed"

# Delete Lambda event source mapping
echo "Deleting Lambda event source mapping..."
EVENT_SOURCE_UUID=$(aws lambda list-event-source-mappings \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --query 'EventSourceMappings[0].UUID' \
    --output text 2>/dev/null || echo "None")
if [ "$EVENT_SOURCE_UUID" != "None" ]; then
    aws lambda delete-event-source-mapping \
        --uuid "$EVENT_SOURCE_UUID" \
        --region "$REGION" || handle_error "Lambda event source mapping deletion failed"
fi

# Delete Lambda function
echo "Deleting Lambda function '$LAMBDA_FUNCTION_NAME'..."
aws lambda delete-function \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --region "$REGION" || handle_error "Lambda function deletion failed"

# Delete Lambda layer versions
echo "Deleting Lambda layer versions..."
LAYER_VERSIONS=$(aws lambda list-layer-versions \
    --layer-name "$LAYER_NAME" \
    --query 'LayerVersions[*].Version' \
    --output text 2>/dev/null || echo "")
if [ ! -z "$LAYER_VERSIONS" ]; then
    for version in $LAYER_VERSIONS; do
        aws lambda delete-layer-version \
            --layer-name "$LAYER_NAME" \
            --version-number "$version" \
            --region "$REGION" || handle_error "Lambda layer version $version deletion failed"
    done
fi

# Delete S3 objects
echo "Deleting S3 objects..."
aws s3 rm "s3://$BUCKET_NAME/$S3_LAYER_KEY" || handle_error "S3 object deletion failed"

# Delete S3 bucket
echo "Deleting S3 bucket '$BUCKET_NAME'..."
aws s3api delete-bucket \
    --bucket "$BUCKET_NAME" \
    --region "$REGION" || handle_error "S3 bucket deletion failed"

# Delete Kinesis stream
echo "Deleting Kinesis stream '$STREAM_NAME'..."
aws kinesis delete-stream \
    --stream-name "$STREAM_NAME" \
    --region "$REGION" || handle_error "Kinesis stream deletion failed"

# Delete DynamoDB table
echo "Deleting DynamoDB table '$TABLE_NAME'..."
aws dynamodb delete-table \
    --table-name "$TABLE_NAME" \
    --region "$REGION" || handle_error "DynamoDB table deletion failed"

# Detach IAM policies
echo "Detaching IAM policies..."
aws iam detach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole || handle_error "Basic execution policy detachment failed"

aws iam detach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonKinesisFullAccess || handle_error "Kinesis policy detachment failed"

aws iam detach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess || handle_error "DynamoDB policy detachment failed"

aws iam detach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess || handle_error "SageMaker policy detachment failed"

# Delete IAM role
echo "Deleting IAM role '$ROLE_NAME'..."
aws iam delete-role \
    --role-name "$ROLE_NAME" || handle_error "IAM role deletion failed"

echo "AWS services deletion process completed!" 