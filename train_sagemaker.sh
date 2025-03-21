#!/bin/bash

# =============== Configuration Section ===============
# AWS Region Configuration
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Project Configuration
PROJECT_NAME="stock-analysis"
ENVIRONMENT="dev"

# SageMaker Configuration
SAGEMAKER_BUCKET="kevinw-p2"
SAGEMAKER_PREFIX="sagemaker"
TRAINING_JOB_NAME="${PROJECT_NAME}-training-$(date +%Y%m%d-%H%M%S)"
TRAINING_IMAGE="763104351884.dkr.ecr.us-east-1.amazonaws.com/pytorch-training:1.8.1-cpu-py36-ubuntu18.04"
TRAINING_INSTANCE_TYPE="ml.t2.medium"
TRAINING_INSTANCE_COUNT=1
TRAINING_VOLUME_SIZE=5
TRAINING_MAX_RUNTIME=3600
TRAINING_HYPERPARAMETERS='{
    "epochs": "100",
    "batch-size": "32",
    "learning-rate": "0.001",
    "model-type": "lstm"
}'

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

function wait_for_training() {
    local job_name="$1"
    local max_retries=60
    local retry_count=0
    
    echo "Waiting for training job '$job_name' to complete..."
    while [ $retry_count -lt $max_retries ]; do
        status=$(aws sagemaker describe-training-job \
            --training-job-name "$job_name" \
            --region "$REGION" \
            --query 'TrainingJobStatus' \
            --output text 2>/dev/null || echo "Starting")
        
        if [ "$status" = "Completed" ]; then
            echo "Training job completed successfully!"
            return 0
        elif [ "$status" = "Failed" ]; then
            echo "Training job failed!"
            failure_reason=$(aws sagemaker describe-training-job \
                --training-job-name "$job_name" \
                --region "$REGION" \
                --query 'FailureReason' \
                --output text)
            echo "Failure reason: $failure_reason"
            exit 1
        elif [ "$status" = "InProgress" ] || [ "$status" = "Starting" ]; then
            echo "Training is still in progress... (attempt $((retry_count + 1))/$max_retries)"
            sleep 30
            retry_count=$((retry_count + 1))
        else
            echo "Unexpected status: $status"
            exit 1
        fi
    done
    
    echo "Timeout waiting for training job to complete"
    exit 1
}

# =============== Execution Section ===============
# Check for required tools
check_command "aws"

# Check IAM role and permissions
check_iam_role

# Start training job
echo "Starting training job '$TRAINING_JOB_NAME'..."
aws sagemaker create-training-job \
    --training-job-name "$TRAINING_JOB_NAME" \
    --algorithm-specification '{
        "TrainingImage": "'$TRAINING_IMAGE'",
        "TrainingInputMode": "File",
        "AlgorithmName": "Custom"
    }' \
    --role-arn "arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME" \
    --hyper-parameters "$TRAINING_HYPERPARAMETERS" \
    --input-data-config '[
        {
            "ChannelName": "train",
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": "s3://'$SAGEMAKER_BUCKET'/'$SAGEMAKER_PREFIX'/train/",
                    "S3DataDistributionType": "FullyReplicated"
                }
            }
        },
        {
            "ChannelName": "validation",
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": "s3://'$SAGEMAKER_BUCKET'/'$SAGEMAKER_PREFIX'/validation/",
                    "S3DataDistributionType": "FullyReplicated"
                }
            }
        }
    ]' \
    --output-data-config '{
        "S3OutputPath": "s3://'$SAGEMAKER_BUCKET'/'$SAGEMAKER_PREFIX'/output/"
    }' \
    --resource-config '{
        "InstanceCount": '$TRAINING_INSTANCE_COUNT',
        "InstanceType": "'$TRAINING_INSTANCE_TYPE'",
        "VolumeSizeInGB": '$TRAINING_VOLUME_SIZE'
    }' \
    --stopping-condition '{
        "MaxRuntimeInSeconds": '$TRAINING_MAX_RUNTIME'
    }' \
    --region "$REGION" || { echo "Training job creation failed"; exit 1; }

# Wait for training to complete
wait_for_training "$TRAINING_JOB_NAME"

echo "Model training completed successfully!" 