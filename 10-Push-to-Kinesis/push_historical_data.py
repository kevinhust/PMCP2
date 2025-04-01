import yfinance as yf
import boto3
import json
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_last_trading_days(n_days=2):
    """
    Get a list of the most recent trading days.
    """
    today = datetime.now(ZoneInfo("America/New_York"))
    trading_days = []
    current_day = today
    
    while len(trading_days) < n_days:
        if current_day.weekday() < 5:  # Monday = 0, Sunday = 6
            trading_days.append(current_day.strftime('%Y-%m-%d'))
        current_day -= timedelta(days=1)
    
    return trading_days

def push_historical_data_to_kinesis():
    """
    Push historical stock data to Kinesis Stream.
    """
    # Configure boto3
    kinesis = boto3.client('kinesis')
    stream_name = 'stock-stream'
    stock_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]
    
    # Test Kinesis connection
    try:
        kinesis.describe_stream(StreamName=stream_name)
        logger.info(f"Successfully connected to Kinesis stream: {stream_name}")
    except Exception as e:
        logger.error(f"Error connecting to Kinesis: {str(e)}")
        return
    
    # Get the last 2 trading days
    trading_days = get_last_trading_days(2)
    logger.info(f"Processing data for trading days: {trading_days}")
    
    total_records = 0
    
    # Process each stock
    for stock_symbol in stock_symbols:
        logger.info(f"Processing stock: {stock_symbol}")
        
        # Process each trading day
        for day in trading_days:
            try:
                # Get data for the current day
                stock = yf.Ticker(stock_symbol)
                data = stock.history(start=day, end=(datetime.strptime(day, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d'), interval='1h')
                
                if data.empty:
                    logger.warning(f"No data available for {stock_symbol} on {day}")
                    continue
                
                # Process each hour
                for index, row in data.iterrows():
                    record = {
                        'symbol': stock_symbol,
                        'timestamp': index.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'open': float(row['Open']),
                        'high': float(row['High']),
                        'low': float(row['Low']),
                        'close': float(row['Close']),
                        'volume': int(row['Volume'])
                    }
                    
                    # Send record to Kinesis
                    try:
                        kinesis.put_record(
                            StreamName=stream_name,
                            Data=json.dumps(record),
                            PartitionKey=record['symbol']
                        )
                        total_records += 1
                        if total_records % 100 == 0:
                            logger.info(f"Processed {total_records} records so far...")
                    except Exception as e:
                        logger.error(f"Error sending record to Kinesis: {str(e)}")
                        continue
                    
                    # Add a small delay to avoid rate limits
                    time.sleep(0.1)
                
                logger.info(f"Completed processing for {stock_symbol} on {day}. Total records so far: {total_records}")
                
            except Exception as e:
                logger.error(f"Error processing {stock_symbol} for day {day}: {str(e)}")
                continue
    
    logger.info(f"Data import completed. Total records sent: {total_records}")

if __name__ == "__main__":
    push_historical_data_to_kinesis()