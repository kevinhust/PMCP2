#!/bin/bash

# --- Configuration ---
AWS_REGION="us-east-1"  # Change to your desired region
KINESIS_STREAM_NAME="stock-stream"
DYNAMODB_TABLE_NAME="stock-table"
S3_BUCKET_NAME="kevinw-p2"
ECS_CLUSTER_NAME="stock-analysis-cluster"
ECS_SERVICE_NAME="stock-data-collector"
ECS_TASK_FAMILY="stock-data-collector"
IAM_ROLE_NAME="StockAnalysisRole"
SAGEMAKER_MODEL_NAME="tsla-stock-predictor-model"  # Replace with your model name
SAGEMAKER_ENDPOINT_CONFIG_NAME="tsla-stock-predictor-config" # Replace
SAGEMAKER_ENDPOINT_NAME="tsla-stock-predictor" # Replace
HISTORICAL_DATA_FILE="tsla_history.csv" # Local path to historical data
MODEL_ARTIFACT_FILE="model.tar.gz"  # Local Path or S3 path
# LAMBDA_LAYER_FILE="ta_lib_layer.zip" # Local Path  -- REMOVED Lambda Layer

# --- Helper Functions ---

# Check if an AWS CLI profile is configured
check_aws_profile() {
    if ! aws configure list | grep -q "profile"; then
        echo "Error: AWS CLI profile is not configured. Please configure your AWS credentials."
        exit 1
    fi
}

# Check if a command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "Error: $1 is not installed. Please install it and try again."
        exit 1
    fi
}

# Create or update an IAM role
create_or_update_iam_role() {
  local role_name="$1"
  local trust_policy_file="$2"
  local policy_arns="$3" # Comma-separated list of ARNs

    # Check if the role already exists
  if aws iam get-role --role-name "$role_name" &> /dev/null; then
    echo "IAM role '$role_name' already exists. Updating trust policy..."
    # Update the trust policy if the role exists
        aws iam update-assume-role-policy \
      --role-name "$role_name" \
      --policy-document "file://$trust_policy_file"
  else
    echo "Creating IAM role '$role_name'..."
    aws iam create-role \
      --role-name "$role_name" \
      --assume-role-policy-document "file://$trust_policy_file"
  fi

  # Attach policies
    IFS=',' read -r -a policy_arn_array <<< "$policy_arns"
  for arn in "${policy_arn_array[@]}"; do
    echo "Attaching policy '$arn' to role '$role_name'..."
    aws iam attach-role-policy --role-name "$role_name" --policy-arn "$arn"
  done
}


# --- Pre-Deployment Checks ---

check_aws_profile
check_command aws
check_command jq # Required for parsing JSON output
check_command docker # Required for ECS deployment


# --- 1. Create Kinesis Data Stream ---

echo "Creating Kinesis data stream: $KINESIS_STREAM_NAME..."
aws kinesis create-stream \
    --stream-name "$KINESIS_STREAM_NAME" \
    --shard-count 1 \
    --region "$AWS_REGION"
# Wait for the stream to become active.  Retry for up to 5 minutes.
retries=30
delay=10
while [ $retries -gt 0 ]; do
    stream_status=$(aws kinesis describe-stream --stream-name "$KINESIS_STREAM_NAME" --region "$AWS_REGION" | jq -r '.StreamDescription.StreamStatus')
    if [ "$stream_status" == "ACTIVE" ]; then
        echo "Kinesis stream is active."
        break
    fi
    echo "Waiting for Kinesis stream to become active (Status: $stream_status)..."
    sleep "$delay"
    retries=$((retries - 1))
done

if [ $retries -eq 0 ]; then
    echo "Error: Kinesis stream did not become active within the timeout period."
    exit 1
fi

# --- 2. Create DynamoDB Table ---

echo "Creating DynamoDB table: $DYNAMODB_TABLE_NAME..."

# Check if the table already exists
if aws dynamodb describe-table --table-name "$DYNAMODB_TABLE_NAME" --region "$AWS_REGION" &> /dev/null; then
  echo "DynamoDB table '$DYNAMODB_TABLE_NAME' already exists."
else
  aws dynamodb create-table \
    --table-name "$DYNAMODB_TABLE_NAME" \
    --attribute-definitions \
        AttributeName=stock_symbol,AttributeType=S \
        AttributeName=timestamp,AttributeType=S \
    --key-schema \
        AttributeName=stock_symbol,KeyType=HASH \
        AttributeName=timestamp,KeyType=RANGE \
    --provisioned-throughput \
        ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region "$AWS_REGION"
      # Wait for the table to become active
    aws dynamodb wait table-exists --table-name "$DYNAMODB_TABLE_NAME" --region "$AWS_REGION"
    echo "DynamoDB table created."
fi


# --- 3. Create S3 Bucket (if it doesn't exist) ---

echo "Checking for S3 bucket: $S3_BUCKET_NAME..."
if aws s3api head-bucket --bucket "$S3_BUCKET_NAME" --region "$AWS_REGION" 2>&1 | grep -q "Not Found"; then
    echo "Creating S3 bucket: $S3_BUCKET_NAME..."
    aws s3api create-bucket \
        --bucket "$S3_BUCKET_NAME" \
        --region "$AWS_REGION" \
        --create-bucket-configuration LocationConstraint="$AWS_REGION"
        # Make the bucket private (block public access)
    aws s3api put-public-access-block \
        --bucket "$S3_BUCKET_NAME" \
        --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
else
    echo "S3 bucket '$S3_BUCKET_NAME' already exists."
fi


# --- 4. Upload Historical Data and Model to S3 ---
echo "Uploading historical data to S3: $HISTORICAL_DATA_FILE -> s3://$S3_BUCKET_NAME/$HISTORICAL_DATA_FILE"
aws s3 cp "$HISTORICAL_DATA_FILE" "s3://$S3_BUCKET_NAME/$HISTORICAL_DATA_FILE"

echo "Uploading model artifact to S3: $MODEL_ARTIFACT_FILE -> s3://$S3_BUCKET_NAME/$MODEL_ARTIFACT_FILE"
aws s3 cp "$MODEL_ARTIFACT_FILE" "s3://$S3_BUCKET_NAME/$MODEL_ARTIFACT_FILE"

# --- 5. IAM Role ---

# Create trust policy files (inline policies are limited in size)
cat >ecs_task_trust_policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "",
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF


cat >lambda_trust_policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF


# Define policy ARNs (split for readability)
ecs_policy_arns="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy,arn:aws:iam::aws:policy/CloudWatchLogsFullAccess,arn:aws:iam::aws:policy/AmazonKinesisFullAccess"
lambda_policy_arns="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole,arn:aws:iam::aws:policy/AmazonKinesisFullAccess,arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess,arn:aws:iam::aws:policy/AmazonSageMakerFullAccess,arn:aws:iam::aws:policy/AmazonS3FullAccess"

# Create or update the IAM role for ECS
create_or_update_iam_role "$IAM_ROLE_NAME-ecs" "ecs_task_trust_policy.json" "$ecs_policy_arns"
# Create or update the IAM role for Lambda
create_or_update_iam_role "$IAM_ROLE_NAME-lambda" "lambda_trust_policy.json" "$lambda_policy_arns"


# Get the ECS role ARN (needed for task definition)
ECS_ROLE_ARN=$(aws iam get-role --role-name "$IAM_ROLE_NAME-ecs" --query 'Role.Arn' --output text)


# --- 6. ECS Cluster ---
echo "Creating ECS cluster: $ECS_CLUSTER_NAME..."
aws ecs create-cluster --cluster-name "$ECS_CLUSTER_NAME" --region "$AWS_REGION"

# --- 7. ECS Task Definition ---
#  Create a task definition (replace with your actual Docker image URI).

# Get Account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)

cat >ecs_task_definition.json <<EOF
{
  "family": "$ECS_TASK_FAMILY",
  "executionRoleArn": "$ECS_ROLE_ARN",
  "taskRoleArn": "$ECS_ROLE_ARN",
  "networkMode": "awsvpc",
  "requiresCompatibilities": [
    "FARGATE"
  ],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "stock-data-collector",
      "image": "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/stock-data-collector:latest",
      "essential": true,
      "environment": [
        {
          "name": "KINESIS_STREAM_NAME",
          "value": "$KINESIS_STREAM_NAME"
        },
        {
          "name": "TICKER_SYMBOL",
          "value": "TSLA"
        },
        {
          "name": "DATA_COLLECTION_INTERVAL",
          "value": "10"
        },
        {
          "name": "AWS_REGION",
          "value": "$AWS_REGION"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/$ECS_TASK_FAMILY",
          "awslogs-region": "$AWS_REGION",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
EOF
echo "Registering ECS task definition..."
aws ecs register-task-definition --cli-input-json file://ecs_task_definition.json --region "$AWS_REGION"

# --- 8. ECS Service ---
echo "Creating ECS service: $ECS_SERVICE_NAME..."
aws ecs create-service \
    --cluster "$ECS_CLUSTER_NAME" \
    --service-name "$ECS_SERVICE_NAME" \
    --task-definition "$ECS_TASK_FAMILY" \
    --desired-count 1 \
    --launch-type "FARGATE" \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxxxxxxxxxxxxxxx],securityGroups=[sg-xxxxxxxxxxxxxxxxx],assignPublicIp=ENABLED}" \
    --region "$AWS_REGION"
#   --platform-version "LATEST" \ # Removed, use default

echo "ECS service created.  It may take a few minutes for the task to start."

# --- 9. SageMaker ---
# 9.1 Model
echo "Creating SageMaker model: $SAGEMAKER_MODEL_NAME..."

# Primary container environment, adjust as needed for your model
container_env=$(jq -n \
    --arg image "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/your-sagemaker-image:latest" \
    --arg model_data_url "s3://$S3_BUCKET_NAME/$MODEL_ARTIFACT_FILE" \
    '{Image: $image, Mode: "SingleModel", ModelDataUrl: $model_data_url}')


aws sagemaker create-model \
    --model-name "$SAGEMAKER_MODEL_NAME" \
    --primary-container "$container_env" \
    --execution-role-arn "$ECS_ROLE_ARN" \
    --region "$AWS_REGION"

# 9.2 Endpoint Configuration
echo "Creating SageMaker endpoint configuration: $SAGEMAKER_ENDPOINT_CONFIG_NAME..."
aws sagemaker create-endpoint-config \
    --endpoint-config-name "$SAGEMAKER_ENDPOINT_CONFIG_NAME" \
    --production-variants "VariantName=variant-1,ModelName=$SAGEMAKER_MODEL_NAME,InitialInstanceCount=1,InstanceType=ml.t2.medium,InitialVariantWeight=1.0" \
     --region "$AWS_REGION"

# 9.3 Endpoint
echo "Creating SageMaker endpoint: $SAGEMAKER_ENDPOINT_NAME..."
aws sagemaker create-endpoint \
    --endpoint-name "$SAGEMAKER_ENDPOINT_NAME" \
    --endpoint-config-name "$SAGEMAKER_ENDPOINT_CONFIG_NAME" \
    --region "$AWS_REGION"

echo "SageMaker endpoint creation initiated. It takes several minutes to complete."
aws sagemaker wait endpoint-in-service --endpoint-name "$SAGEMAKER_ENDPOINT_NAME" --region "$AWS_REGION"
echo "SageMaker endpoint is in service."

# # 10. Lambda Layer (Optional - for ta-lib) -- REMOVED Lambda Layer Section
# if [ -f "$LAMBDA_LAYER_FILE" ]; then  # Only create if the file exists
#   echo "Creating Lambda Layer for ta-lib..."

#   # Publish the layer
#   layer_response=$(aws lambda publish-layer-version \
#     --layer-name "ta-lib-layer" \
#     --description "TA-Lib for Python" \
#     --content "ZipFile=$(base64 -w 0 "$LAMBDA_LAYER_FILE")" \
#     --compatible-runtimes python3.9 python3.8 python3.7 python3.10 python3.11 python3.12\
#      --region "$AWS_REGION")

#     # Extract Layer Version ARN
#     LAYER_VERSION_ARN=$(echo "$layer_response" | jq -r '.LayerVersionArn')
#     echo "Lambda Layer ARN: $LAYER_VERSION_ARN"
# else
#     echo "Skipping Lambda Layer creation.  File not found: $LAMBDA_LAYER_FILE"
# fi

echo "Deployment script completed.  Please configure the Kinesis trigger for your Lambda function manually."

# Clean up the temporary files
rm ecs_task_trust_policy.json lambda_trust_policy.json ecs_task_definition.json