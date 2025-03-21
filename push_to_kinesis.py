import yfinance as yf
import boto3
import time
import json
import logging
import os
import signal
import sys
from botocore.exceptions import ClientError
from datetime import datetime, timezone
from typing import Dict, Any, List
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('stock_data.log')
    ]
)
logger = logging.getLogger(__name__)

# Configuration
REGION = os.environ.get('AWS_REGION', 'us-east-1')
STREAM_NAME = os.environ.get('KINESIS_STREAM', 'stock-stream')
DEFAULT_SYMBOLS = os.environ.get('STOCK_SYMBOLS', 'TSLA,MSFT,AAPL').split(',')
RETRY_ATTEMPTS = int(os.environ.get('RETRY_ATTEMPTS', '3'))
SLEEP_INTERVAL = int(os.environ.get('SLEEP_INTERVAL', '60'))
MAX_ERRORS = int(os.environ.get('MAX_ERRORS', '5'))
TRADING_HOURS_ONLY = os.environ.get('TRADING_HOURS_ONLY', 'true').lower() == 'true'

# Initialize Kinesis client
kinesis_client = boto3.client('kinesis', region_name=REGION)

def is_trading_hours() -> bool:
    """
    Check if current time is within US market trading hours (9:30 AM - 4:00 PM EST)
    """
    if not TRADING_HOURS_ONLY:
        return True
        
    now = datetime.now(timezone.utc)
    est_time = now.astimezone(timezone.timezone('America/New_York'))
    
    # Check if it's a weekday
    if est_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
        
    # Check if it's within trading hours
    trading_start = est_time.replace(hour=9, minute=30, second=0, microsecond=0)
    trading_end = est_time.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return trading_start <= est_time <= trading_end

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
            'open': float(latest['Open']),
            'market_cap': stock.info.get('marketCap', None),
            'day_high': float(latest['High']),
            'day_low': float(latest['Low']),
            'prev_close': stock.info.get('previousClose', None)
        }
    except Exception as e:
        logger.error(f"Failed to fetch stock data for {symbol}: {str(e)}")
        raise

def process_symbols(symbols: List[str]) -> None:
    """
    Process multiple stock symbols
    
    Args:
        symbols: List of stock symbols to process
    """
    errors_count = 0
    
    while True:
        try:
            if not is_trading_hours():
                logger.info("Outside trading hours. Waiting...")
                time.sleep(SLEEP_INTERVAL)
                continue
                
            for symbol in symbols:
                try:
                    stock_data = get_stock_data(symbol)
                    send_to_kinesis(stock_data)
                    logger.info(f"Successfully processed data for {symbol}")
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {str(e)}")
                    errors_count += 1
                    if errors_count >= MAX_ERRORS:
                        raise
                    continue
                    
            errors_count = 0  # Reset error counter after successful processing
            
        except Exception as e:
            errors_count += 1
            logger.error(f"Error in main loop: {str(e)}")
            
            if errors_count >= MAX_ERRORS:
                logger.critical(f"Too many consecutive errors ({errors_count}). Exiting...")
                raise
            
            # Increase wait time after error
            time.sleep(SLEEP_INTERVAL * (errors_count + 1))
            continue
            
        time.sleep(SLEEP_INTERVAL)

def signal_handler(signum, frame):
    """
    Handle shutdown signals
    """
    logger.info("Received shutdown signal. Cleaning up...")
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        symbols = os.environ.get('STOCK_SYMBOLS', ','.join(DEFAULT_SYMBOLS)).split(',')
        logger.info(f"Starting stock data collection for symbols: {symbols}")
        logger.info(f"Update interval: {SLEEP_INTERVAL} seconds")
        logger.info(f"Trading hours only: {TRADING_HOURS_ONLY}")
        process_symbols(symbols)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down...")
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}")
        raise