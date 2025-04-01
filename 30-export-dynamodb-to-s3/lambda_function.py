import logging
import os
import json
import boto3
import pandas as pd
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize DynamoDB and S3 clients
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

def lambda_handler(event, context):
    """
    Lambda handler for exporting DynamoDB data to S3 and updating QuickSight manifest.
    """
    try:
        # Get environment variables
        table_name = os.environ['DYNAMO_TABLE']
        bucket_name = os.environ['S3_BUCKET']
        s3_prefix = os.environ['S3_PREFIX']

        # Log environment variables
        logging.info(f"DYNAMO_TABLE: {table_name}, S3_BUCKET: {bucket_name}, S3_PREFIX: {s3_prefix}")

        # Query DynamoDB table
        items = query_dynamodb(table_name)

        # Process DynamoDB items
        new_records = process_dynamodb_items(items)

        if not new_records:
            logging.info("No new records to process.")
            return {
                'statusCode': 200,
                'body': 'No records to process'
            }

        # Convert new records to DataFrame
        new_df = pd.DataFrame(new_records)

        # Define S3 key (single CSV file)
        s3_key = f"{s3_prefix}/stock_data.csv"

        # Update CSV in S3
        update_csv_in_s3(bucket_name, s3_key, new_df)

        # Update manifest file for QuickSight
        manifest_key = f"{s3_prefix}/stock_data_manifest.json"
        update_quicksight_manifest(bucket_name, manifest_key, s3_key)

        return {
            'statusCode': 200,
            'body': f"Successfully processed {len(new_records)} records to s3://{bucket_name}/{s3_key}"
        }

    except Exception as e:
        logging.exception("An error occurred during processing:")
        return {
            'statusCode': 500,
            'body': f"An error occurred: {str(e)}"
        }

def query_dynamodb(table_name):
    """
    Queries the DynamoDB table and returns the items.
    """
    table = dynamodb.Table(table_name)
    try:
        response = table.scan()
        items = response['Items']
        logging.info(f"Successfully scanned DynamoDB table {table_name}. Found {len(items)} items.")
        return items
    except ClientError as e:
        logging.error(f"Failed to query DynamoDB table {table_name}: {e}")
        raise

def process_dynamodb_items(items):
    """
    Processes the DynamoDB items and returns a list of new records.
    """
    new_records = []
    for item in items:
        try:
            logging.info(f"Processing DynamoDB item: {item}")
            if 'symbol' not in item:
                logging.warning(f"Missing 'symbol' in DynamoDB item. Skipping item.")
                continue

            technical_signals = item.get('signals', {})
            signal = item.get('signal', 'HOLD')
            confidence = item.get('confidence', 0.0)

            new_records.append({
                'symbol': str(item['symbol']),
                'timestamp': int(item['timestamp']) if 'timestamp' in item else None,
                'current_price': float(item['current_price']) if 'current_price' in item else None,
                'signal': str(signal),
                'confidence': float(confidence),
                'rsi': float(technical_signals.get('RSI', 50.0)),
                'macd': float(technical_signals.get('MACD', 0.0)),
                'bb_upper': float(technical_signals.get('BB_Upper', 0.0)),
                'bb_lower': float(technical_signals.get('BB_Lower', 0.0)),
                'stoch_k': float(technical_signals.get('Stoch_K', 50.0)),
                'stoch_d': float(technical_signals.get('Stoch_D', 50.0)),
                'ma_5': float(technical_signals.get('MA_5', 0.0)),
                'ma_20': float(technical_signals.get('MA_20', 0.0)),
                'volume': int(technical_signals.get('Volume', 0))
            })
        except Exception as e:
            logging.warning(f"Error processing DynamoDB item: {e}. Skipping item.")
            continue

    logging.info(f"Processed {len(new_records)} DynamoDB items.")
    return new_records

def update_csv_in_s3(bucket_name, s3_key, new_df):
    """
    Updates the CSV file in S3 with the new data.
    """
    try:
        # Read existing CSV from S3 (if exists)
        try:
            response = s3.get_object(Bucket=bucket_name, Key=s3_key)
            existing_df = pd.read_csv(response['Body'])
            updated_df = pd.concat([existing_df, new_df], ignore_index=True)
            logging.info(f"Successfully read existing CSV from s3://{bucket_name}/{s3_key}")
        except s3.exceptions.NoSuchKey:
            updated_df = new_df
            logging.info(f"No existing CSV found at s3://{bucket_name}/{s3_key}. Creating new CSV.")

        # Save updated DataFrame to CSV
        csv_buffer = updated_df.to_csv(index=False)

        # Upload updated CSV to S3
        s3.put_object(Bucket=bucket_name, Key=s3_key, Body=csv_buffer)
        logging.info(f"Successfully uploaded updated CSV to s3://{bucket_name}/{s3_key}")

    except ClientError as e:
        logging.error(f"Failed to read or upload CSV to S3: {e}")
        raise

def update_quicksight_manifest(bucket_name, manifest_key, s3_key):
    """
    Updates the QuickSight manifest file in S3.
    """
    manifest = {
        "fileLocations": [
            {
                "URIs": [
                    f"s3://{bucket_name}/{s3_key}"
                ]
            }
        ]
    }
    try:
        s3.put_object(
            Bucket=bucket_name,
            Key=manifest_key,
            Body=json.dumps(manifest)
        )
        logging.info(f"Successfully uploaded manifest to s3://{bucket_name}/{manifest_key}")
    except ClientError as e:
        logging.error(f"Failed to upload manifest to S3: {e}")
        raise