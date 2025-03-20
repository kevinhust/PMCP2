import yfinance as yf
import boto3
import time
import json
import logging
import os
from botocore.exceptions import ClientError
from datetime import datetime
from typing import Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
REGION = os.environ.get('AWS_REGION', 'us-east-1')
STREAM_NAME = os.environ.get('KINESIS_STREAM', 'stock-stream')
DEFAULT_SYMBOL = os.environ.get('STOCK_SYMBOL', 'TSLA')
RETRY_ATTEMPTS = 3
SLEEP_INTERVAL = 60  # seconds

# Initialize Kinesis client
kinesis_client = boto3.client('kinesis', region_name=REGION)

@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def send_to_kinesis(data: Dict[str, Any], stream_name: str = STREAM_NAME) -> None:
    """
    Send data to Kinesis data stream
    
    Args:
        data: Dictionary containing data to send
        stream_name: Name of the Kinesis stream
    
    Raises:
        ClientError: When AWS API call fails
    """
    try:
        response = kinesis_client.put_record(
            StreamName=stream_name,
            Data=json.dumps(data),
            PartitionKey=data['stock_symbol']
        )
        logger.info(f"Successfully sent data to Kinesis. Sequence number: {response['SequenceNumber']}")
    except ClientError as e:
        logger.error(f"Failed to send data to Kinesis: {str(e)}")
        raise

def get_stock_data(symbol: str) -> Dict[str, Any]:
    """
    Get stock data
    
    Args:
        symbol: Stock symbol
    
    Returns:
        Dictionary containing stock data
    
    Raises:
        Exception: When fetching stock data fails
    """
    try:
        stock = yf.Ticker(symbol)
        data = stock.history(period="1d", interval="1m")
        if data.empty:
            raise ValueError(f"No data available for symbol {symbol}")
        
        latest = data.iloc[-1]
        current_time = datetime.utcnow()
        
        return {
            'stock_symbol': symbol,
            'price': float(latest['Close']),
            'volume': int(latest['Volume']),
            'timestamp': int(time.time()),
            'datetime': current_time.isoformat(),
            'high': float(latest['High']),
            'low': float(latest['Low']),
            'open': float(latest['Open'])
        }
    except Exception as e:
        logger.error(f"Failed to fetch stock data for {symbol}: {str(e)}")
        raise

def fetch_realtime_data(symbol: str = DEFAULT_SYMBOL) -> None:
    """
    Continuously fetch and push real-time stock data
    
    Args:
        symbol: Stock symbol
    """
    logger.info(f"Starting real-time data fetch for {symbol}")
    errors_count = 0
    
    while True:
        try:
            stock_data = get_stock_data(symbol)
            send_to_kinesis(stock_data)
            logger.info(f"Successfully processed data for {symbol}")
            errors_count = 0  # Reset error counter
            
        except Exception as e:
            errors_count += 1
            logger.error(f"Error processing data: {str(e)}")
            
            if errors_count >= RETRY_ATTEMPTS:
                logger.critical(f"Too many consecutive errors ({errors_count}). Exiting...")
                raise
            
            # Increase wait time after error
            time.sleep(SLEEP_INTERVAL * (errors_count + 1))
            continue
            
        time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    try:
        symbol = os.environ.get('STOCK_SYMBOL', DEFAULT_SYMBOL)
        fetch_realtime_data(symbol)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down...")
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}")
        raise