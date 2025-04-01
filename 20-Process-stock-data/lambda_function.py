import json
import boto3
import pandas as pd
import numpy as np
from datetime import datetime
import logging
import os
import base64
from decimal import Decimal
import pytz
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
DYNAMO_TABLE = os.environ.get('DYNAMO_TABLE', 'stock-indicators')

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMO_TABLE)

def fetch_historical_data(symbol, current_timestamp, lookback_minutes=30):
    """
    Fetch historical data for a given symbol from DynamoDB (last 30 minutes).
    """
    try:
        lookback_timestamp = current_timestamp - (lookback_minutes * 60)
        response = table.query(
            KeyConditionExpression="symbol = :symbol AND #ts >= :ts",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":symbol": symbol,
                ":ts": lookback_timestamp
            }
        )
        items = response.get('Items', [])
        logger.info(f"Fetched {len(items)} historical records for {symbol}")
        return items
    except Exception as e:
        logger.error(f"Error fetching historical data for {symbol}: {str(e)}")
        return []

def calculate_rsi(data, timeperiod=14):
    delta = pd.Series(data).diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=timeperiod).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=timeperiod).mean()
    loss = loss.replace(0, np.nan)
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calculate_macd(data, fastperiod=12, slowperiod=26, signalperiod=9):
    """Calculate MACD"""
    fast_ema = pd.Series(data).ewm(span=fastperiod, adjust=False).mean()
    slow_ema = pd.Series(data).ewm(span=slowperiod, adjust=False).mean()
    macd = fast_ema - slow_ema
    signal = macd.ewm(span=signalperiod, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist

def calculate_bollinger_bands(data, timeperiod=20, nbdevup=2, nbdevdn=2):
    """Calculate Bollinger Bands"""
    sma = pd.Series(data).rolling(window=timeperiod).mean()
    rolling_std = pd.Series(data).rolling(window=timeperiod).std()
    upper = sma + (rolling_std * nbdevup)
    lower = sma - (rolling_std * nbdevdn)
    return upper, sma, lower

def calculate_stochastic_oscillator(high, low, close, fastk_period=14, slowk_period=3, slowd_period=3):
    """Calculate Stochastic Oscillator"""
    lowest_low = pd.Series(low).rolling(window=fastk_period).min()
    highest_high = pd.Series(high).rolling(window=fastk_period).max()
    fastk = 100 * (pd.Series(close) - lowest_low) / (highest_high - lowest_low)
    slowk = fastk.rolling(window=slowk_period).mean()
    slowd = slowk.rolling(window=slowd_period).mean()
    return slowk, slowd

def calculate_ma(data, period):
    """Calculate Moving Average"""
    return pd.Series(data).rolling(window=period).mean()

def calculate_technical_signals(stock_data, historical_data):
    """
    Calculate technical indicators and signals based on historical data.
    """
    try:
        # Add current data to historical data
        all_data = historical_data + [{
            'close': float(stock_data['close']),
            'high': float(stock_data['high']),
            'low': float(stock_data['low']),
            'volume': int(stock_data['volume'])
        }]

        # Sort by timestamp
        all_data = sorted(all_data, key=lambda x: x.get('timestamp', 0))

        # Extract time series data
        close_prices = [float(item['close']) for item in all_data]
        high_prices = [float(item['high']) for item in all_data]
        low_prices = [float(item['low']) for item in all_data]
        volumes = [int(item['volume']) for item in all_data]

        # Return neutral signals if not enough data
        if len(close_prices) < 30:  # Need at least 30 minutes of data
            return {
                'MA_5': close_prices[-1],
                'MA_20': close_prices[-1],
                'MA_50': close_prices[-1],
                'RSI': 50.0,
                'MACD': 0.0,
                'MACD_Signal': 0.0,
                'BB_Upper': close_prices[-1] * 1.02,
                'BB_Lower': close_prices[-1] * 0.98,
                'BB_Middle': close_prices[-1],
                'Stoch_K': 50.0,
                'Stoch_D': 50.0,
                'Volume': volumes[-1],
                'MA_Signal': 0,
                'RSI_Signal': 0,
                'MACD_Signal': 0,
                'BB_Signal': 0,
                'Stoch_Signal': 0
            }

        # Calculate technical indicators
        # RSI
        rsi = calculate_rsi(close_prices, timeperiod=14)
        latest_rsi = float(rsi.iloc[-1])

        # MACD
        macd, signal, _ = calculate_macd(close_prices, fastperiod=12, slowperiod=26, signalperiod=9)
        latest_macd = float(macd.iloc[-1])
        latest_signal = float(signal.iloc[-1])
        prev_macd = float(macd.iloc[-2]) if len(macd) > 1 else latest_macd
        prev_signal = float(signal.iloc[-2]) if len(signal) > 1 else latest_signal

        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(close_prices, timeperiod=20)
        latest_bb_upper = float(bb_upper.iloc[-1])
        latest_bb_middle = float(bb_middle.iloc[-1])
        latest_bb_lower = float(bb_lower.iloc[-1])

        # Stochastic Oscillator
        stoch_k, stoch_d = calculate_stochastic_oscillator(high_prices, low_prices, close_prices)
        latest_stoch_k = float(stoch_k.iloc[-1])
        latest_stoch_d = float(stoch_d.iloc[-1])
        prev_stoch_k = float(stoch_k.iloc[-2]) if len(stoch_k) > 1 else latest_stoch_k
        prev_stoch_d = float(stoch_d.iloc[-2]) if len(stoch_d) > 1 else latest_stoch_d

        # Moving Averages
        ma5 = calculate_ma(close_prices, period=5)
        ma20 = calculate_ma(close_prices, period=20)
        ma50 = calculate_ma(close_prices, period=50)  # Used for trend filtering
        latest_ma5 = float(ma5.iloc[-1])
        latest_ma20 = float(ma20.iloc[-1])
        latest_ma50 = float(ma50.iloc[-1]) if len(ma50) > 1 else latest_ma20
        prev_ma5 = float(ma5.iloc[-2]) if len(ma5) > 1 else latest_ma5
        prev_ma20 = float(ma20.iloc[-2]) if len(ma20) > 1 else latest_ma20

        # Generate signals for each indicator
        # RSI signal
        rsi_signal = 0
        if latest_rsi > 70:
            rsi_signal = -1  # Sell
        elif latest_rsi < 30:
            rsi_signal = 1   # Buy

        # MACD signal
        macd_signal = 0
        if prev_macd < prev_signal and latest_macd > latest_signal:
            macd_signal = 1  # Golden Cross, Buy
        elif prev_macd > prev_signal and latest_macd < latest_signal:
            macd_signal = -1  # Death Cross, Sell

        # Bollinger Bands signal
        bb_signal = 0
        latest_close = close_prices[-1]
        if latest_close > latest_bb_upper:
            bb_signal = -1  # Breakout above upper band, Sell
        elif latest_close < latest_bb_lower:
            bb_signal = 1   # Breakout below lower band, Buy

        # Stochastic Oscillator signal
        stoch_signal = 0
        if prev_stoch_k < prev_stoch_d and latest_stoch_k > latest_stoch_d and latest_stoch_k < 20:
            stoch_signal = 1  # Golden Cross and oversold, Buy
        elif prev_stoch_k > prev_stoch_d and latest_stoch_k < latest_stoch_d and latest_stoch_k > 80:
            stoch_signal = -1  # Death Cross and overbought, Sell

        # Moving Average signal
        ma_signal = 0
        if prev_ma5 < prev_ma20 and latest_ma5 > latest_ma20:
            ma_signal = 1  # Golden Cross, Buy
        elif prev_ma5 > prev_ma20 and latest_ma5 < latest_ma20:
            ma_signal = -1  # Death Cross, Sell

        # Trend filtering (using MA50)
        trend_direction = 1 if latest_close > latest_ma50 else -1

        # Apply trend filtering
        if trend_direction == 1:  # Overall trend up
            if ma_signal == -1:
                ma_signal = 0  # Ignore sell signal
            if rsi_signal == -1:
                rsi_signal = 0
            if macd_signal == -1:
                macd_signal = 0
            if bb_signal == -1:
                bb_signal = 0
            if stoch_signal == -1:
                stoch_signal = 0
        else:  # Overall trend down
            if ma_signal == 1:
                ma_signal = 0  # Ignore buy signal
            if rsi_signal == 1:
                rsi_signal = 0
            if macd_signal == 1:
                macd_signal = 0
            if bb_signal == 1:
                bb_signal = 0
            if stoch_signal == 1:
                stoch_signal = 0

        return {
            'MA_5': latest_ma5,
            'MA_20': latest_ma20,
            'MA_50': latest_ma50,
            'RSI': latest_rsi,
            'MACD': latest_macd,
            'MACD_Signal': latest_signal,
            'BB_Upper': latest_bb_upper,
            'BB_Lower': latest_bb_lower,
            'BB_Middle': latest_bb_middle,
            'Stoch_K': latest_stoch_k,
            'Stoch_D': latest_stoch_d,
            'Volume': volumes[-1],
            'MA_Signal': ma_signal,
            'RSI_Signal': rsi_signal,
            'MACD_Signal': macd_signal,
            'BB_Signal': bb_signal,
            'Stoch_Signal': stoch_signal
        }
    except Exception as e:
        logger.error(f"Error calculating technical signals: {str(e)}")
        raise

def analyze_signals(signals):
    """
    Perform weighted voting to determine final buy/sell signal.
    """
    weights = {
        'MA_Signal': 0.3,
        'RSI_Signal': 0.2,
        'MACD_Signal': 0.2,
        'BB_Signal': 0.15,
        'Stoch_Signal': 0.15
    }

    score = 0
    total_weight = 0
    for signal, weight in weights.items():
        signal_value = signals.get(signal, 0)
        if signal_value != 0:
            score += signal_value * weight
            total_weight += weight

    final_signal = "HOLD"
    confidence = abs(score) if total_weight > 0 else 0
    if total_weight > 0:
        if score > 0.3:
            final_signal = "BUY"
        elif score < -0.3:
            final_signal = "SELL"

    return {
        'signal': final_signal,
        'confidence': float(confidence)
    }

def convert_timestamp(timestamp_str):
    """Convert timestamp string to Unix timestamp (seconds since epoch)"""
    try:
        if isinstance(timestamp_str, (int, float)):
            return int(timestamp_str)
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S%z")
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        return int(dt.timestamp())
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        raise

def validate_item(item):
    """Validate and convert data item types"""
    if not isinstance(item, dict):
        raise ValueError("Item must be a dictionary")
    required_fields = ['symbol', 'timestamp']
    for field in required_fields:
        if field not in item:
            raise ValueError(f"Missing required field: {field}")
    if not isinstance(item['symbol'], str):
        raise ValueError("symbol must be a string")
    if 'timestamp' in item:
        item['timestamp'] = convert_timestamp(item['timestamp'])
    return item

def float_to_decimal(value):
    """Convert various numeric types to Decimal for DynamoDB compatibility"""
    if value is None:
        return None
    elif isinstance(value, (np.int64, np.int32, np.int16, np.int8)):
        return int(value)
    elif isinstance(value, (np.float64, np.float32, np.float16)):
        if np.isnan(value) or np.isinf(value):
            return Decimal('0')
        return Decimal(str(float(value)))
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            return Decimal('0')
        return Decimal(str(value))
    elif isinstance(value, dict):
        return {k: float_to_decimal(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [float_to_decimal(v) for v in value]
    return value

def store_prediction(result):
    """
    Store prediction results in DynamoDB.
    """
    try:
        result = validate_item(result)
        item = float_to_decimal(result)
        table.put_item(Item=item)
        logger.info(f"Successfully stored prediction for {result['symbol']} at {result['timestamp']}")
    except Exception as e:
        logger.error(f"Error storing to DynamoDB: {str(e)}")
        raise

def lambda_handler(event, context):
    """
    Lambda handler for processing Kinesis records.
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        if 'Records' not in event:
            raise ValueError("No Records found in event")
            
        for record in event['Records']:
            try:
                payload = base64.b64decode(record['kinesis']['data'])
                stock_data = json.loads(payload)
                logger.info(f"Processing record for symbol: {stock_data.get('symbol')}")

                current_timestamp = convert_timestamp(stock_data['timestamp'])
                historical_data = fetch_historical_data(stock_data['symbol'], current_timestamp)
                
                # Modify data format to match historical data format
                stock_data_formatted = {
                    'close': stock_data['close'],
                    'high': stock_data['high'],
                    'low': stock_data['low'],
                    'volume': stock_data['volume']
                }
                
                signals = calculate_technical_signals(stock_data_formatted, historical_data)
                signal_analysis = analyze_signals(signals)

                result = {
                    'symbol': stock_data['symbol'],
                    'timestamp': current_timestamp,
                    'current_price': float(stock_data['close']),
                    'signal': signal_analysis['signal'],
                    'confidence': float(signal_analysis['confidence']),
                    'signals': signals,
                    'open': float(stock_data['open']),
                    'high': float(stock_data['high']),
                    'low': float(stock_data['low']),
                    'volume': int(stock_data['volume'])
                }

                store_prediction(result)
                
            except Exception as e:
                logger.error(f"Error processing record: {str(e)}")
                continue
                
        return {
            'statusCode': 200,
            'body': json.dumps('Successfully processed records')
        }
        
    except Exception as e:
        logger.error(f"Error processing records: {str(e)}")
        raise