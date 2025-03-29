import boto3
import pandas as pd
import os
import json
import time

dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

def lambda_handler(event, context):
    # Get environment variables
    table_name = os.environ['DYNAMO_TABLE']
    bucket_name = os.environ['S3_BUCKET']
    s3_prefix = os.environ['S3_PREFIX']

    # Delay for 15 seconds to ensure process-stock-data has completed
    time.sleep(15)

    # Query DynamoDB table
    table = dynamodb.Table(table_name)
    try:
        response = table.scan()
        items = response['Items']
    except Exception as e:
        return {
            'statusCode': 500,
            'body': f"Failed to query DynamoDB: {str(e)}"
        }

    # Process DynamoDB items
    new_records = []
    for item in items:
        new_records.append({
            'symbol': item['symbol'],
            'timestamp': int(item['timestamp']),
            'current_price': float(item['current_price']),
            'macd': float(item['macd']),
            'rsi': float(item['rsi']),
            'bb_upper': float(item['bb_upper']),
            'bb_lower': float(item['bb_lower']),
            'volume': int(item['volume'])
        })

    if not new_records:
        return {
            'statusCode': 200,
            'body': 'No records to process'
        }

    # Convert new records to DataFrame
    new_df = pd.DataFrame(new_records)

    # Read existing CSV from S3 (if exists)
    s3_key = f"{s3_prefix}/stock_data.csv"
    try:
        existing_csv = s3.get_object(Bucket=bucket_name, Key=s3_key)
        existing_df = pd.read_csv(existing_csv['Body'])
        updated_df = pd.concat([existing_df, new_df], ignore_index=True)
    except s3.exceptions.NoSuchKey:
        updated_df = new_df
    except Exception as e:
        return {
            'statusCode': 500,
            'body': f"Failed to read or append CSV: {str(e)}"
        }

    # Save updated DataFrame to CSV
    csv_buffer = updated_df.to_csv(index=False)

    # Upload updated CSV to S3
    try:
        s3.put_object(Bucket=bucket_name, Key=s3_key, Body=csv_buffer)
    except Exception as e:
        return {
            'statusCode': 500,
            'body': f"Failed to upload CSV to S3: {str(e)}"
        }

    # Update manifest file for QuickSight
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
            Key=f"{s3_prefix}/stock_data_manifest.json",
            Body=json.dumps(manifest)
        )
    except Exception as e:
        return {
            'statusCode': 500,
            'body': f"Failed to upload manifest to S3: {str(e)}"
        }

    return {
        'statusCode': 200,
        'body': f"Successfully processed {len(new_records)} records to s3://{bucket_name}/{s3_key}"
    }