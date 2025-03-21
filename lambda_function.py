import json
import boto3
import os
import time
import logging
import datetime
from typing import Dict, Union, List
import numpy as np
from decimal import Decimal
from botocore.exceptions import ClientError
import talib
import base64
from boto3.dynamodb.conditions import Key

# --- Configuration ---
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME', 'stock-table')
SAGEMAKER_ENDPOINT_NAME = os.environ.get('SAGEMAKER_ENDPOINT_NAME', 'tsla-stock-predictor')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

# --- Constants ---
MA_PERIODS = [5, 20, 50]  # Different Moving Average periods
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BBANDS_PERIOD = 20
BBANDS_STDDEV = 2
FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]  # Common Fibonacci levels
STOCH_K = 14  # Stochastic %K period
STOCH_D = 3   # Stochastic %D period

# --- AWS Clients ---
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE_NAME)
sagemaker_runtime = boto3.client('sagemaker-runtime', region_name=AWS_REGION)

# --- Setup Logging ---
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Decimal Encoder for JSON ---
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def calculate_indicators(historical_data: List[Dict[str, Union[str, float]]]) -> Dict[str, Decimal]:
    """
    Calculate technical indicators.
    """
    if not historical_data:
        return {}

    prices = np.array([float(item['price']) for item in historical_data])
    volumes = np.array([float(item['volume']) for item in historical_data], dtype=np.float64)

    indicators = {}

    try:
        # Moving Averages (MA)
        for period in MA_PERIODS:
            if len(prices) >= period:
                indicators[f'MA{period}'] = Decimal(str(talib.SMA(prices, timeperiod=period)[-1]))
            else:
                indicators[f'MA{period}'] = Decimal('0')

        # Relative Strength Index (RSI)
        if len(prices) >= RSI_PERIOD:
            indicators['RSI'] = Decimal(str(talib.RSI(prices, timeperiod=RSI_PERIOD)[-1]))
        else:
            indicators['RSI'] = Decimal('0')

        # MACD
        if len(prices) >= (MACD_SLOW + MACD_SIGNAL - 1):
            macd, macdsignal, machhist = talib.MACD(prices, fastperiod=MACD_FAST, slowperiod=MACD_SLOW, signalperiod=MACD_SIGNAL)
            indicators['MACD'] = Decimal(str(macd[-1]))
            indicators['Signal'] = Decimal(str(macdsignal[-1]))
            indicators['Hist'] = Decimal(str(machhist[-1]))
        else:
            indicators['MACD'] = indicators['Signal'] = indicators['Hist'] = Decimal('0')

        # Bollinger Bands
        if len(prices) >= BBANDS_PERIOD:
            upperband, middleband, lowerband = talib.BBANDS(prices, timeperiod=BBANDS_PERIOD, nbdevup=BBANDS_STDDEV, nbdevdn=BBANDS_STDDEV, matype=0)
            indicators['BB_Upper'] = Decimal(str(upperband[-1]))
            indicators['BB_Middle'] = Decimal(str(middleband[-1]))
            indicators['BB_Lower'] = Decimal(str(lowerband[-1]))
        else:
            indicators['BB_Upper'] = indicators['BB_Middle'] = indicators['BB_Lower'] = Decimal('0')

        # Stochastic Oscillator
        if len(prices) >= STOCH_K:
            slowk, slowd = talib.STOCH(prices, prices, prices, fastk_period=STOCH_K, slowk_period=STOCH_D, slowk_matype=0, slowd_period=STOCH_D, slowd_matype=0)
            indicators['Stoch_K'] = Decimal(str(slowk[-1]))
            indicators['Stoch_D'] = Decimal(str(slowd[-1]))
        else:
            indicators['Stoch_K'] = indicators['Stoch_D'] = Decimal('0')

        # Volume (use the last volume value)
        indicators['Volume'] = Decimal(str(volumes[-1]))

        # Fibonacci Retracement (based on the last 100 periods, or all available)
        if len(prices) >= 100:
            high = np.max(prices[-100:])
            low = np.min(prices[-100:])
        else:
            high = np.max(prices)
            low = np.min(prices)
        diff = high - low
        for level in FIB_LEVELS:
            indicators[f'Fib_{level}'] = Decimal(str(high - diff * level))

    except Exception as e:
        logger.error(f"Error calculating indicators: {e}")
        return {}

    return indicators

def invoke_sagemaker_endpoint(data: Dict[str, Union[str, Decimal]], endpoint_name: str) -> str:
    """
    Invoke the SageMaker endpoint for prediction.
    """
    try:
        # Define the key indicators required by the model
        required_indicators = ['price', 'Volume'] + [f'MA{period}' for period in MA_PERIODS] + ['RSI', 'MACD', 'Signal','BB_Upper','BB_Middle','BB_Lower','Stoch_K','Stoch_D']
        for level in FIB_LEVELS:
            required_indicators.append(f'Fib_{level}')

        # Check if all required indicators are available and not zero
        if all(key in data and float(data[key]) != 0.0 for key in required_indicators):

            # Prepare input data
            input_data_list = [
                float(data['price']),
                float(data['Volume'])
            ]
            # Add MA values
            for period in MA_PERIODS:
                input_data_list.append(float(data[f'MA{period}']))
            # Add other indicators
            input_data_list.extend([
                float(data['RSI']),
                float(data['MACD']),
                float(data['Signal']),
                float(data['BB_Upper']),
                float(data['BB_Middle']),
                float(data['BB_Lower']),
            ])
            # Add Fibonacci levels
            for level in FIB_LEVELS:
                input_data_list.append(float(data[f'Fib_{level}']))
            # Add Stochastic
            input_data_list.extend([
                float(data['Stoch_K']),
                float(data['Stoch_D']),
            ])
            # Convert the list to a comma-separated string
            input_data = ",".join(map(str, input_data_list))

            response = sagemaker_runtime.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType='text/csv',
                Body=input_data.encode('utf-8')
            )
            prediction = response['Body'].read().decode('utf-8').strip()
            return prediction
        else:
            logger.info("Not enough data to calculate all required indicators, skipping prediction")
            return "SKIPPED"

    except Exception as e:
        logger.error(f"Error invoking SageMaker endpoint: {e}")
        return "ERROR"

def write_to_dynamodb(data: Dict[str, Union[str, Decimal]], table_name: str):
    """
    Write data to DynamoDB.
    """
    try:
        # DynamoDB handles Decimal natively
        response = table.put_item(Item=data)
        logger.info(f"Successfully wrote data for stock_symbol: {data['stock_symbol']}")

    except Exception as e:
        logger.error(f"Error writing to DynamoDB: {e}")

def process_record(record: Dict, historical_data: List[Dict]) -> Union[Dict, None]:
    """Process a single Kinesis record."""
    try:
        data_bytes = record['kinesis']['data']
        data_string = base64.b64decode(data_bytes).decode('utf-8')
        data = json.loads(data_string)
        logger.info(f"Received data: {data}")

        # Preserve the original timestamp, use current time as fallback
        data['timestamp'] = Decimal(str(data.get('timestamp', time.time())))
        data['datetime'] = datetime.datetime.now().isoformat()

        # Convert fields to Decimal
        data['price'] = Decimal(str(data['price']))
        data['volume'] = Decimal(str(data['volume']))

        indicators = calculate_indicators(historical_data + [data]) # Pass combined data
        data.update(indicators)

        prediction = invoke_sagemaker_endpoint(data, SAGEMAKER_ENDPOINT_NAME)

        if prediction not in ["ERROR", "SKIPPED"]:
            data['prediction'] = "UP" if float(prediction) > 0.5 else "DOWN"
            data['prediction_value'] = Decimal(str(prediction))

        write_to_dynamodb(data, DYNAMODB_TABLE_NAME)
        return data

    except Exception as e:
        logger.error(f"Error in process_record: {e}")
        return None

def lambda_handler(event, context):
    """
    Lambda function handler.
    """
    try:
        historical_data = []
        processed_records = []

        # Assume all records are for the same stock, fetch historical data once
        if event['Records']:
            first_record = event['Records'][0]
            data_bytes = first_record['kinesis']['data']
            data_string = base64.b64decode(data_bytes).decode('utf-8')
            sample_data = json.loads(data_string)
            stock_symbol = sample_data['stock_symbol']

            required_points = max(max(MA_PERIODS), MACD_SLOW + MACD_SIGNAL - 1, BBANDS_PERIOD, STOCH_K, 100)  # Include 100 for Fibonacci
            response = table.query(
                KeyConditionExpression=Key('stock_symbol').eq(stock_symbol),
                ScanIndexForward=False,
                Limit=required_points
            )
            # Sort by timestamp ascending
            historical_data = sorted(response.get('Items', []), key=lambda x: x['timestamp'])

        for record in event['Records']:
            processed_data = process_record(record, historical_data) # Pass existing data
            if processed_data:
                processed_records.append(processed_data)
                historical_data.append(processed_data) # Append new data, keep only recent.
                historical_data = sorted(historical_data, key=lambda x: x['timestamp'])[-required_points:] # Keep recent


        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Data processed successfully',
                'processed_records': len(processed_records)
            }, cls=DecimalEncoder)
        }

    except Exception as e:
        logger.error(f"Error in Lambda handler: {e}")
        return {'statusCode': 500, 'body': json.dumps('Error processing data', cls=DecimalEncoder)}