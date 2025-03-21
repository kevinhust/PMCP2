import json
import time
import boto3
import yfinance as yf
import datetime
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
KINESIS_STREAM_NAME = os.environ.get('KINESIS_STREAM_NAME', 'stock-stream')
TICKER_SYMBOL = os.environ.get('TICKER_SYMBOL', 'TSLA')  # Get ticker from environment, default to TSLA
DATA_COLLECTION_INTERVAL = int(os.environ.get('DATA_COLLECTION_INTERVAL', 10)) # Default 10 seconds
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')  # Default to us-east-1

# --- AWS Clients ---
kinesis_client = boto3.client('kinesis', region_name=AWS_REGION)

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
        # Using .info can be rate limited, so we get the minimal data needed.
        #  We prioritize 'currentPrice' and 'volume', falling back to less reliable fields if necessary
        data = ticker.fast_info
        price = data.lastPrice
        volume = data.lastVolume
        timestamp = datetime.datetime.now().isoformat()
        stock_data = {
            'stock_symbol': ticker_symbol,
            'price': price,
            'volume': volume,
            'timestamp': timestamp
        }
        return stock_data

    except Exception as e:
        logging.error(f"Error fetching data for {ticker_symbol}: {e}")
        return None

def put_to_kinesis(data, stream_name):
    """
    Puts data to the specified Kinesis stream.

    Args:
        data (dict): The data to put.
        stream_name (str): The name of the Kinesis stream.
    """
    try:
        if data:  # Only send if data was successfully retrieved.
            payload = json.dumps(data)
            # Use stock_symbol as the partition key for better distribution and ordering within the shard
            response = kinesis_client.put_record(
                StreamName=stream_name,
                Data=payload,
                PartitionKey=data['stock_symbol']
            )
            logging.info(f"Successfully sent data to Kinesis. ShardId: {response['ShardId']}, SequenceNumber: {response['SequenceNumber']}")

    except Exception as e:
        logging.error(f"Error putting data to Kinesis: {e}")

def main():
    """
    Main function to continuously fetch and push stock data to Kinesis.
    """
    logging.info(f"Starting data collection for {TICKER_SYMBOL} every {DATA_COLLECTION_INTERVAL} seconds.")
    logging.info(f"Pushing data to Kinesis stream: {KINESIS_STREAM_NAME}")
    
    while True:
        try:
            stock_data = get_stock_data(TICKER_SYMBOL)
            put_to_kinesis(stock_data, KINESIS_STREAM_NAME)
            time.sleep(DATA_COLLECTION_INTERVAL)
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            # Implement a more robust error handling/retry mechanism.  Simple exponential backoff for now.
            time.sleep(60)


if __name__ == "__main__":
    main()