import os
import json
import boto3
import logging
from alpha_vantage.timeseries import TimeSeries
from ratelimit import limits, sleep_and_retry

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables
KINESIS_STREAM_NAME = os.environ['KINESIS_STREAM_NAME']
STOCK_SYMBOLS = os.environ['STOCK_SYMBOLS'].split(',')
ALPHA_VANTAGE_API_KEY = os.environ['ALPHA_VANTAGE_API_KEY']

# Initialize Kinesis client
kinesis_client = boto3.client('kinesis')

# Rate limiting for Alpha Vantage API (5 calls per minute)
@sleep_and_retry
@limits(calls=5, period=60)
def rate_limit():
    pass

def get_stock_data(ticker_symbol):
    try:
        rate_limit()
        ts = TimeSeries(key=ALPHA_VANTAGE_API_KEY)
        data, meta_data = ts.get_intraday(symbol=ticker_symbol, interval='1min', outputsize='compact')
        if not data:
            raise ValueError("No data returned from Alpha Vantage")
        latest_timestamp = sorted(data.keys())[-1]
        latest_data = data[latest_timestamp]
        stock_data = {
            'symbol': ticker_symbol,
            'timestamp': latest_timestamp,
            'open': float(latest_data['1. open']),
            'high': float(latest_data['2. high']),
            'low': float(latest_data['3. low']),
            'close': float(latest_data['4. close']),
            'volume': int(latest_data['5. volume'])
        }
        logging.info(f"Fetched stock data for {ticker_symbol}: {stock_data}")
        return stock_data
    except Exception as e:
        logging.error(f"Error fetching data for {ticker_symbol}: {e}")
        raise

def put_to_kinesis(data, stream_name):
    try:
        if data:
            payload = json.dumps(data)
            response = kinesis_client.put_record(
                StreamName=stream_name,
                Data=payload.encode('utf-8'),
                PartitionKey=data['symbol']  
            )
            logging.info(f"Successfully sent data to Kinesis. ShardId: {response['ShardId']}, SequenceNumber: {response['SequenceNumber']}")
            logging.debug(f"Pushed data: {payload}")
    except Exception as e:
        logging.error(f"Error putting data to Kinesis: {e}")
        raise

def lambda_handler(event, context):
    """
    Lambda handler to fetch stock data and push to Kinesis.
    """
    try:
        logging.info(f"Fetching data for {STOCK_SYMBOLS} and pushing to Kinesis stream: {KINESIS_STREAM_NAME}")
        for symbol in STOCK_SYMBOLS:
            try:
                stock_data = get_stock_data(symbol)
                if stock_data:
                    put_to_kinesis(stock_data, KINESIS_STREAM_NAME)
                else:
                    logging.warning(f"Failed to fetch stock data for {symbol}")
            except Exception as e:
                logging.error(f"Error processing symbol {symbol}: {e}")
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