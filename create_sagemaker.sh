#!/bin/bash

# =============== Configuration Section ===============
# AWS Region Configuration
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Project Configuration
PROJECT_NAME="stock-analysis"
ENVIRONMENT="dev"

# SageMaker Configuration
SAGEMAKER_ENDPOINT="tsla-stock-predictor"
SAGEMAKER_CONFIG_NAME="${SAGEMAKER_ENDPOINT}-config"
SAGEMAKER_MODEL_NAME="tsla-stock-model"
SAGEMAKER_BUCKET="kevinw-p2"
SAGEMAKER_PREFIX="sagemaker"

# IAM Configuration
ROLE_NAME="StockAnalysisRole"

# =============== Helper Functions ===============
function check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "$1 is not installed. Please install it first."
        exit 1
    fi
}

function check_iam_role() {
    echo "Checking if IAM role '$ROLE_NAME' exists..."
    if ! aws iam get-role --role-name "$ROLE_NAME" --region "$REGION" > /dev/null 2>&1; then
        echo "Error: IAM role '$ROLE_NAME' does not exist!"
        echo "Please run deploy_aws_services.sh first to create the role."
        exit 1
    fi
    
    # Check if role has necessary SageMaker permissions
    echo "Checking SageMaker permissions for role '$ROLE_NAME'..."
    POLICIES=$(aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[*].PolicyName' --output text)
    REQUIRED_POLICIES=("AmazonSageMakerFullAccess" "AmazonS3FullAccess")
    
    for POLICY in "${REQUIRED_POLICIES[@]}"; do
        if ! echo "$POLICIES" | grep -q "$POLICY"; then
            echo "Error: Role '$ROLE_NAME' is missing required policy '$POLICY'!"
            echo "Please run deploy_aws_services.sh first to attach the required policies."
            exit 1
        fi
    done
    
    echo "IAM role '$ROLE_NAME' exists and has required permissions."
}

function wait_for_resource() {
    local resource_type="$1"
    local resource_name="$2"
    local max_retries=30
    local retry_count=0
    
    echo "Waiting for $resource_type '$resource_name' to be ready..."
    while [ $retry_count -lt $max_retries ]; do
        case "$resource_type" in
            "model")
                status=$(aws sagemaker describe-model \
                    --model-name "$resource_name" \
                    --region "$REGION" \
                    --query 'ModelStatus' \
                    --output text 2>/dev/null || echo "CREATING")
                ;;
            "endpoint-config")
                status=$(aws sagemaker describe-endpoint-config \
                    --endpoint-config-name "$resource_name" \
                    --region "$REGION" \
                    --query 'EndpointConfigStatus' \
                    --output text 2>/dev/null || echo "CREATING")
                ;;
            "endpoint")
                status=$(aws sagemaker describe-endpoint \
                    --endpoint-name "$resource_name" \
                    --region "$REGION" \
                    --query 'EndpointStatus' \
                    --output text 2>/dev/null || echo "CREATING")
                ;;
            *)
                echo "Unknown resource type: $resource_type"
                exit 1
                ;;
        esac
        
        if [ "$status" = "InService" ]; then
            echo "$resource_type '$resource_name' is now ready!"
            return 0
        elif [ "$status" = "Creating" ]; then
            echo "$resource_type is still creating... (attempt $((retry_count + 1))/$max_retries)"
            sleep 10
            retry_count=$((retry_count + 1))
        else
            echo "Unexpected status: $status"
            exit 1
        fi
    done
    
    echo "Timeout waiting for $resource_type to become ready"
    exit 1
}

# =============== Execution Section ===============
# Check for required tools
check_command "aws"

# Check IAM role and permissions
check_iam_role

# Create SageMaker model
echo "Creating SageMaker model '$SAGEMAKER_MODEL_NAME'..."
aws sagemaker create-model \
    --model-name "$SAGEMAKER_MODEL_NAME" \
    --execution-role-arn "arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME" \
    --primary-container '{
        "Image": "763104351884.dkr.ecr.us-east-1.amazonaws.com/pytorch-training:1.8.1-cpu-py36-ubuntu18.04",
        "ModelDataUrl": "s3://'$SAGEMAKER_BUCKET'/'$SAGEMAKER_PREFIX'/model/model.tar.gz",
        "Environment": {
            "SAGEMAKER_PROGRAM": "inference.py"
        }
    }' \
    --region "$REGION" || { echo "SageMaker model creation failed"; exit 1; }

# Wait for model to be ready
wait_for_resource "model" "$SAGEMAKER_MODEL_NAME"

# Create endpoint configuration
echo "Creating endpoint configuration '$SAGEMAKER_CONFIG_NAME'..."
aws sagemaker create-endpoint-config \
    --endpoint-config-name "$SAGEMAKER_CONFIG_NAME" \
    --production-variants '[
        {
            "VariantName": "AllTraffic",
            "ModelName": "'$SAGEMAKER_MODEL_NAME'",
            "InstanceType": "ml.t2.medium",
            "InitialInstanceCount": 1
        }
    ]' \
    --region "$REGION" || { echo "Endpoint configuration creation failed"; exit 1; }

# Wait for endpoint configuration to be ready
wait_for_resource "endpoint-config" "$SAGEMAKER_CONFIG_NAME"

# Create endpoint
echo "Creating endpoint '$SAGEMAKER_ENDPOINT'..."
aws sagemaker create-endpoint \
    --endpoint-name "$SAGEMAKER_ENDPOINT" \
    --endpoint-config-name "$SAGEMAKER_CONFIG_NAME" \
    --region "$REGION" || { echo "Endpoint creation failed"; exit 1; }

# Wait for endpoint to be ready
wait_for_resource "endpoint" "$SAGEMAKER_ENDPOINT"

echo "SageMaker infrastructure deployment completed successfully!" 