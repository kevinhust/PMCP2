import yfinance as yf
import boto3
import time
import json

# Initialize Kinesis client
kinesis_client = boto3.client('kinesis', region_name='us-east-1')

# Function to send data to Kinesis
def send_to_kinesis(data, stream_name='stock-stream'):
    kinesis_client.put_record(
        StreamName=stream_name,
        Data=json.dumps(data),
        PartitionKey=data['stock_symbol']
    )

# Fetch and push real-time data
def fetch_realtime_data(symbol="TSLA"):
    stock = yf.Ticker(symbol)
    while True:
        data = stock.history(period="1d", interval="1m")
        latest = data.iloc[-1]
        result = {
            'stock_symbol': symbol,
            'price': float(latest['Close']),
            'volume': int(latest['Volume']),
            'timestamp': int(time.time())
        }
        send_to_kinesis(result)
        print("Sent to Kinesis:", result)
        time.sleep(60)

if __name__ == "__main__":
    fetch_realtime_data("TSLA")