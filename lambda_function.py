import boto3
import json
import talib
import numpy as np
import os
import logging
from datetime import datetime
from botocore.exceptions import ClientError
from decimal import Decimal

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ.get('DYNAMODB_TABLE', 'stock-table'))
runtime = boto3.client('sagemaker-runtime')
endpoint_name = os.environ.get('SAGEMAKER_ENDPOINT', 'tsla-stock-predictor')

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def calculate_indicators(data_list):
    """
    Calculate technical indicators
    """
    try:
        prices = [float(d['price']) for d in data_list]
        if len(prices) >= 20:
            prices_array = np.array(prices, dtype=np.float64)
            ma20 = talib.SMA(prices_array, timeperiod=20)[-1]
            macd, signal, hist = talib.MACD(
                prices_array, 
                fastperiod=12, 
                slowperiod=26, 
                signalperiod=9
            )
            
            return {
                'ma20': Decimal(str(float(ma20))),
                'macd': Decimal(str(float(macd[-1]))),
                'signal': Decimal(str(float(signal[-1]))),
                'hist': Decimal(str(float(hist[-1])))
            }
        return {}
    except Exception as e:
        logger.error(f"Error calculating indicators: {str(e)}")
        return {}

def predict(data):
    """
    Make predictions using SageMaker endpoint
    """
    try:
        # Prepare prediction data
        prediction_data = [
            float(data['price']),
            float(data['volume']),
            float(data['indicator']['ma20']),
            float(data['indicator']['macd']),
            float(data['indicator']['signal'])
        ]
        
        # Call SageMaker endpoint
        response = runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType='application/json',
            Body=json.dumps(prediction_data)
        )
        
        prediction_result = json.loads(response['Body'].read().decode())
        return Decimal(str(prediction_result[0]))
    except Exception as e:
        logger.error(f"Error making prediction: {str(e)}")
        return None

def process_record(record, historical_data):
    """
    Process a single Kinesis record
    """
    try:
        # Decode and parse data
        payload = json.loads(record['kinesis']['data'])
        
        # Add timestamp
        current_time = datetime.utcnow()
        payload['timestamp'] = Decimal(str(current_time.timestamp()))
        payload['datetime'] = current_time.isoformat()
        
        # Ensure correct numeric types
        payload['price'] = Decimal(str(payload['price']))
        payload['volume'] = Decimal(str(payload['volume']))
        
        # Add to historical data
        historical_data.append(payload)
        
        # Calculate technical indicators
        indicators = calculate_indicators(historical_data)
        if indicators:
            payload['indicator'] = indicators
            prediction = predict(payload)
            if prediction is not None:
                payload['prediction'] = 'UP' if prediction > 0.5 else 'DOWN'
                payload['prediction_value'] = prediction
        
        # Store in DynamoDB
        table.put_item(Item=payload)
        logger.info(f"Successfully processed record for {payload.get('stock_symbol')}")
        
        return payload
    except Exception as e:
        logger.error(f"Error processing record: {str(e)}")
        return None

def lambda_handler(event, context):
    """
    Lambda handler function
    """
    try:
        historical_data = []
        processed_records = []
        
        for record in event['Records']:
            processed_record = process_record(record, historical_data)
            if processed_record:
                processed_records.append(processed_record)
        
        response = {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Processing completed',
                'processed_records': len(processed_records)
            }, cls=DecimalEncoder)
        }
        
        logger.info(f"Successfully processed {len(processed_records)} records")
        return response
        
    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'Error processing records'
            })
        }