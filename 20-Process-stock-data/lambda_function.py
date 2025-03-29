import json
import boto3
import pandas as pd
import numpy as np
import talib
from datetime import datetime
import logging
from collections import deque

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables
DYNAMO_TABLE = os.environ['DYNAMO_TABLE']

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMO_TABLE)

# Data buffer (maximum 50 records)
BUFFER_SIZE = 50
data_buffer = deque(maxlen=BUFFER_SIZE)

def calculate_technical_signals(df):
    """
    Calculate technical indicators

    Args:
        df (pd.DataFrame): DataFrame containing historical data with columns: open, high, low, close, volume

    Returns:
        dict: Dictionary containing technical indicators and signals
    """
    signals = {}

    # Moving Averages
    signals['MA_5'] = df['close'].rolling(window=5).mean().iloc[-1]
    signals['MA_20'] = df['close'].rolling(window=20).mean().iloc[-1]
    signals['MA_5_prev'] = df['close'].rolling(window=5).mean().iloc[-2] if len(df) >= 2 else np.nan
    signals['MA_20_prev'] = df['close'].rolling(window=20).mean().iloc[-2] if len(df) >= 2 else np.nan

    # RSI
    signals['RSI'] = talib.RSI(df['close'], timeperiod=14).iloc[-1] if len(df) >= 14 else np.nan

    # MACD
    macd, macdsignal, _ = talib.MACD(df['close'], fastperiod=12, slowperiod=26, signalperiod=9)
    signals['MACD'] = macd.iloc[-1] if len(df) >= 26 else np.nan
    signals['MACD_Signal'] = macdsignal.iloc[-1] if len(df) >= 26 else np.nan
    signals['MACD_prev'] = macd.iloc[-2] if len(df) >= 27 else np.nan
    signals['MACD_Signal_prev'] = macdsignal.iloc[-2] if len(df) >= 27 else np.nan

    # Bollinger Bands
    upper, middle, lower = talib.BBANDS(df['close'], timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    signals['BB_Upper'] = upper.iloc[-1] if len(df) >= 20 else np.nan
    signals['BB_Middle'] = middle.iloc[-1] if len(df) >= 20 else np.nan
    signals['BB_Lower'] = lower.iloc[-1] if len(df) >= 20 else np.nan

    # Stochastic Oscillator
    stoch_k, stoch_d = talib.STOCH(df['high'], df['low'], df['close'], fastk_period=14, slowk_period=3, slowk_matype=0, slowd_period=3, slowd_matype=0)
    signals['Stoch_K'] = stoch_k.iloc[-1] if len(df) >= 14 else np.nan
    signals['Stoch_D'] = stoch_d.iloc[-1] if len(df) >= 14 else np.nan

    # Volume
    signals['Volume'] = df['volume'].iloc[-1]

    # Signals (for weighted voting)
    signals['MA_Signal'] = 1 if (signals['MA_5'] > signals['MA_20'] and signals['MA_5_prev'] <= signals['MA_20_prev']) else (-1 if signals['MA_5'] < signals['MA_20'] and signals['MA_5_prev'] >= signals['MA_20_prev'] else 0)
    signals['RSI_Signal'] = -1 if signals['RSI'] > 70 else (1 if signals['RSI'] < 30 else 0)
    signals['MACD_Signal'] = 1 if (signals['MACD'] > signals['MACD_Signal'] and signals['MACD_prev'] <= signals['MACD_Signal_prev']) else (-1 if signals['MACD'] < signals['MACD_Signal'] and signals['MACD_prev'] >= signals['MACD_Signal_prev'] else 0)
    signals['BB_Signal'] = -1 if df['close'].iloc[-1] > signals['BB_Upper'] else (1 if df['close'].iloc[-1] < signals['BB_Lower'] else 0)
    signals['Stoch_Signal'] = -1 if (signals['Stoch_K'] > 80 and signals['Stoch_D'] > 80) else (1 if signals['Stoch_K'] < 20 and signals['Stoch_D'] < 20 else 0)

    return signals

def analyze_trend(signals):
    """
    Perform weighted voting based on technical indicator signals to determine price trend

    Args:
        signals (dict): Dictionary containing technical indicators and signals

    Returns:
        dict: Dictionary containing trend, confidence, and strength
    """
    # Weighted voting weights
    weights = {
        'MA_Signal': 0.3,      # Moving Average crossover
        'RSI_Signal': 0.2,     # RSI overbought/oversold
        'MACD_Signal': 0.2,    # MACD signal
        'BB_Signal': 0.15,     # Bollinger Band breakout
        'Stoch_Signal': 0.15   # Stochastic Oscillator
    }

    # Calculate weighted score
    score = 0
    total_weight = 0
    for signal, weight in weights.items():
        signal_value = signals.get(signal, 0)
        if signal_value != 0:  # Only consider indicators with clear signals
            score += signal_value * weight
            total_weight += weight

    # Determine trend and confidence
    trend = "NEUTRAL"
    confidence = abs(score) if total_weight > 0 else 0
    if total_weight > 0:
        if score > 0.5:
            trend = "UP"
        elif score < -0.5:
            trend = "DOWN"

    # Calculate signal strength (based on absolute values of RSI and MACD)
    strength = (abs(signals.get('RSI', 50) - 50) / 50 + abs(signals.get('MACD', 0))) / 2

    return {
        'trend': trend,
        'confidence': float(confidence),
        'strength': float(strength)
    }

def store_prediction(result):
    """
    Store trend prediction results in DynamoDB

    Args:
        result (dict): Dictionary containing prediction results
    """
    try:
        table.put_item(
            Item={
                'stock_symbol': result['stock_symbol'],
                'timestamp': result['timestamp'],
                'current_price': result['current_price'],
                'prediction': result['prediction'],
                'confidence': result['confidence'],
                'strength': result['strength'],
                'technical_signals': {
                    'macd': result['signals']['MACD'],
                    'bb_upper': result['signals']['BB_Upper'],
                    'bb_lower': result['signals']['BB_Lower'],
                    'rsi': result['signals']['RSI'],
                    'volume': result['signals']['Volume']
                }
            }
        )
        logging.info(f"Stored prediction for {result['stock_symbol']} at {result['timestamp']}")
    except Exception as e:
        logging.error(f"Error storing to DynamoDB: {str(e)}")
        raise

def lambda_handler(event, context):
    """
    Lambda handler for processing Kinesis records

    Args:
        event: Kinesis event containing stock data
        context: Lambda context

    Returns:
        dict: Response with status and results
    """
    try:
        records = event['Records']
        results = []

        for record in records:
            # Decode Kinesis data
            payload = json.loads(record['kinesis']['data'])
            logging.info(f"Received record: {payload}")

            # Add data to buffer
            data_buffer.append(payload)

            # Convert to DataFrame
            df = pd.DataFrame(list(data_buffer))
            if len(df) < 26:  # Ensure enough data for MACD and other indicators
                logging.warning(f"Insufficient data in buffer ({len(df)} records), need at least 26")
                continue

            # Calculate technical indicators
            signals = calculate_technical_signals(df)

            # Analyze trend
            analysis = analyze_trend(signals)

            # Prepare result
            result = {
                'stock_symbol': payload['stock_symbol'],
                'timestamp': int(datetime.fromisoformat(payload['timestamp'].replace('Z', '+00:00')).timestamp()),
                'current_price': float(payload['close']),
                'prediction': analysis['trend'],
                'confidence': analysis['confidence'],
                'strength': analysis['strength'],
                'signals': signals
            }

            # Store in DynamoDB
            store_prediction(result)
            results.append(result)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Successfully processed records',
                'results': results
            })
        }

    except Exception as e:
        logging.error(f"Error processing records: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }