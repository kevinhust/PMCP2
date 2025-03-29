import json
import boto3
import yfinance as yf
import datetime
import os
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables
KINESIS_STREAM_NAME = os.environ['KINESIS_STREAM_NAME']
TICKER_SYMBOL = os.environ['TICKER_SYMBOL']
AWS_REGION = os.environ['AWS_REGION']

# Initialize Kinesis client
kinesis_client = boto3.client('kinesis', region_name=AWS_REGION)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def get_stock_data(ticker_symbol):
    """
    Fetches real-time stock data from Yahoo Finance.

    Args:
        ticker_symbol (str): The stock ticker symbol (e.g., 'TSLA').

    Returns:
        dict: A dictionary containing the stock data, or None if an error occurs.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        # Get minute-level data (last 1 minute)
        data = ticker.history(period="1d", interval="1m").tail(1)
        if data.empty:
            raise ValueError("No data returned from Yahoo Finance")

        # Extract latest data
        stock_data = {
            'stock_symbol': ticker_symbol,
            'timestamp': data.index[0].strftime('%Y-%m-%dT%H:%M:%S'),  # ISO 8601 format
            'open': float(data['Open'].iloc[0]),
            'high': float(data['High'].iloc[0]),
            'low': float(data['Low'].iloc[0]),
            'close': float(data['Close'].iloc[0]),
            'volume': int(data['Volume'].iloc[0])
        }
        logging.info(f"Fetched stock data for {ticker_symbol}: {stock_data}")
        return stock_data

    except Exception as e:
        logging.error(f"Error fetching data for {ticker_symbol}: {e}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def put_to_kinesis(data, stream_name):
    """
    Puts data to the specified Kinesis stream.

    Args:
        data (dict): The data to put.
        stream_name (str): The name of the Kinesis stream.
    """
    try:
        if data:  # Only send if data was successfully retrieved
            payload = json.dumps(data)
            # Use stock_symbol as PartitionKey
            response = kinesis_client.put_record(
                StreamName=stream_name,
                Data=payload.encode('utf-8'),
                PartitionKey=data['stock_symbol']
            )
            logging.info(f"Successfully sent data to Kinesis. ShardId: {response['ShardId']}, SequenceNumber: {response['SequenceNumber']}")
            logging.debug(f"Pushed data: {payload}")

    except Exception as e:
        logging.error(f"Error putting data to Kinesis: {e}")
        raise

def lambda_handler(event, context):
    """
    Lambda handler to fetch stock data and push it to Kinesis.

    Args:
        event: The event data passed to the Lambda function.
        context: The runtime information of the Lambda function.

    Returns:
        dict: A dictionary containing the status code and response message.
    """
    try:
        logging.info(f"Fetching data for {TICKER_SYMBOL} and pushing to Kinesis stream: {KINESIS_STREAM_NAME}")
        
        # Get stock data
        stock_data = get_stock_data(TICKER_SYMBOL)
        if not stock_data:
            return {
                'statusCode': 500,
                'body': json.dumps('Failed to fetch stock data')
            }

        # Push to Kinesis
        put_to_kinesis(stock_data, KINESIS_STREAM_NAME)

        return {
            'statusCode': 200,
            'body': json.dumps('Data pushed to Kinesis successfully')
        }

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps(f"Error: {str(e)}")
        }