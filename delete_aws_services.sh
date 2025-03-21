#!/bin/bash

# --- Configuration ---
AWS_REGION="us-east-1"
KINESIS_STREAM_NAME="stock-stream"
DYNAMODB_TABLE_NAME="stock-table"
S3_BUCKET_NAME="kevinw-p2"
ECS_CLUSTER_NAME="stock-analysis-cluster"
ECS_SERVICE_NAME="stock-data-collector"
ECS_TASK_FAMILY="stock-data-collector"
IAM_ROLE_NAME="StockAnalysisRole"
SAGEMAKER_MODEL_NAME="tsla-stock-predictor-model"
SAGEMAKER_ENDPOINT_CONFIG_NAME="tsla-stock-predictor-config"
SAGEMAKER_ENDPOINT_NAME="tsla-stock-predictor"

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

# --- Pre-Deletion Checks ---
check_aws_profile
check_command aws

# --- 1. Delete SageMaker Endpoint ---

echo "Deleting SageMaker endpoint: $SAGEMAKER_ENDPOINT_NAME..."
aws sagemaker delete-endpoint --endpoint-name "$SAGEMAKER_ENDPOINT_NAME" --region "$AWS_REGION" || true

# Wait until the endpoint is deleted
retries=30
delay=10
while [ $retries -gt 0 ]; do
    if ! aws sagemaker describe-endpoint --endpoint-name "$SAGEMAKER_ENDPOINT_NAME" --region "$AWS_REGION" &> /dev/null; then
        echo "SageMaker endpoint deleted."
        break
    fi
    echo "Waiting for SageMaker endpoint to be deleted..."
    sleep "$delay"
    retries=$((retries - 1))
done

# --- 2. Delete SageMaker Endpoint Configuration ---

echo "Deleting SageMaker endpoint configuration: $SAGEMAKER_ENDPOINT_CONFIG_NAME..."
aws sagemaker delete-endpoint-config --endpoint-config-name "$SAGEMAKER_ENDPOINT_CONFIG_NAME" --region "$AWS_REGION" || true

# --- 3. Delete SageMaker Model ---

echo "Deleting SageMaker model: $SAGEMAKER_MODEL_NAME..."
aws sagemaker delete-model --model-name "$SAGEMAKER_MODEL_NAME" --region "$AWS_REGION" || true

# --- 4. Delete ECS Service ---

echo "Deleting ECS service: $ECS_SERVICE_NAME..."
# Need to scale the service down to 0 desired tasks first.  Force new deployment to ensure all tasks using the current
# task definition are stopped
aws ecs update-service --cluster "$ECS_CLUSTER_NAME" --service "$ECS_SERVICE_NAME" --desired-count 0 --force-new-deployment --region "$AWS_REGION" || true

# Wait for the service to reach 0 running tasks.
retries=30
delay=10
while [ $retries -gt 0 ]; do
    running_tasks=$(aws ecs describe-services --cluster "$ECS_CLUSTER_NAME" --services "$ECS_SERVICE_NAME" --region "$AWS_REGION" | jq -r '.services[0].runningCount')
    if [ "$running_tasks" == "0" ]; then
        echo "ECS service scaled down to 0."
        break
    fi
    echo "Waiting for ECS service to scale down (Running tasks: $running_tasks)..."
    sleep "$delay"
    retries=$((retries - 1))
done
#Now delete the service
aws ecs delete-service --cluster "$ECS_CLUSTER_NAME" --service "$ECS_SERVICE_NAME" --region "$AWS_REGION"  || true

# --- 5. Delete ECS Task Definition ---

echo "Deregistering ECS task definition: $ECS_TASK_FAMILY..."
# Get the latest revision of the task definition
latest_revision=$(aws ecs describe-task-definition --task-definition "$ECS_TASK_FAMILY" --region "$AWS_REGION" | jq -r '.taskDefinition.revision')

# Deregister *all* revisions of the task definition
for ((i=1; i<=$latest_revision; i++)); do
 aws ecs deregister-task-definition --task-definition "$ECS_TASK_FAMILY:$i" --region "$AWS_REGION" || true
done


# --- 6. Delete ECS Cluster ---

echo "Deleting ECS cluster: $ECS_CLUSTER_NAME..."
aws ecs delete-cluster --cluster "$ECS_CLUSTER_NAME" --region "$AWS_REGION" || true


# --- 7. Delete DynamoDB Table ---

echo "Deleting DynamoDB table: $DYNAMODB_TABLE_NAME..."
aws dynamodb delete-table --table-name "$DYNAMODB_TABLE_NAME" --region "$AWS_REGION" || true

# --- 8. Delete Kinesis Data Stream ---

echo "Deleting Kinesis data stream: $KINESIS_STREAM_NAME..."
aws kinesis delete-stream --stream-name "$KINESIS_STREAM_NAME" --region "$AWS_REGION" || true

# --- 9. Empty and Delete S3 Bucket ---
echo "Emptying S3 bucket: $S3_BUCKET_NAME..."
aws s3 rm "s3://$S3_BUCKET_NAME" --recursive --region "$AWS_REGION" || true # Empty the bucket

echo "Deleting S3 bucket: $S3_BUCKET_NAME..."
aws s3api delete-bucket --bucket "$S3_BUCKET_NAME" --region "$AWS_REGION" || true # Delete empty bucket

# --- 10. Delete IAM Roles ---

# Detach policies before deleting the roles.
for role_suffix in "ecs" "lambda"; do
    role_name="$IAM_ROLE_NAME-$role_suffix"
    echo "Detaching policies from IAM role: $role_name..."

    # List attached policies (both managed and inline)
    policy_arns=$(aws iam list-attached-role-policies --role-name "$role_name" --query 'AttachedPolicies[*].PolicyArn' --output text || true)

    # Detach managed policies
    if [ -n "$policy_arns" ]; then # Check if policy_arns is not empty
      IFS=$'\n' read -r -d '' -a policy_array <<< "$policy_arns"  # Split by newline
      for arn in "${policy_array[@]}"; do
        aws iam detach-role-policy --role-name "$role_name" --policy-arn "$arn"  || true
      done
     fi

    # List and delete inline policies
    inline_policies=$(aws iam list-role-policies --role-name "$role_name" --query 'PolicyNames' --output text || true)
    if [ -n "$inline_policies" ]; then  # Check if inline_policies is not empty
        IFS=$'\n' read -r -d '' -a inline_policy_array <<< "$inline_policies" # Split by newline
        for policy_name in "${inline_policy_array[@]}"; do
            aws iam delete-role-policy --role-name "$role_name" --policy-name "$policy_name" || true
        done
    fi

    echo "Deleting IAM role: $role_name..."
    aws iam delete-role --role-name "$role_name" || true
done

echo "Deletion script completed."