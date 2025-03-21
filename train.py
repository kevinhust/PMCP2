# train.py
import os
import argparse
import pandas as pd
import numpy as np
import yfinance as yf
import talib
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.metrics import mean_squared_error, accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from azureml.core import Run, Workspace, Experiment, ScriptRunConfig, Environment
from azureml.core.compute import ComputeTarget, AmlCompute
from azureml.core.compute_target import ComputeInstance
from azureml.widgets import RunDetails
from azure.identity import DefaultAzureCredential

# 获取运行上下文
try:
    run = Run.get_context()
except Exception as e:
    print(f"Error getting run context: {e}")
    run = None

# 解析参数 (可选，用于配置模型)
parser = argparse.ArgumentParser()
parser.add_argument('--ticker', type=str, default='AAPL', help='股票代码')
parser.add_argument('--n_estimators', type=int, default=100, help='随机森林树的数量')
args = parser.parse_args()

# 数据获取和预处理 (与之前相同)
ticker = args.ticker
start_date = "2020-01-01"
end_date = "2023-12-31"
try:
    data = yf.download(ticker, start=start_date, end=end_date)
    if data.empty:
        raise ValueError(f"No data found for {ticker} on {start_date} to {end_date}")
except Exception as e:
    print(f"Error downloading data: {e}")
    if run:
        run.log('data_download_error', str(e))
    exit(1)

data['MA_5'] = data['Close'].rolling(window=5).mean()
data['MA_10'] = data['Close'].rolling(window=10).mean()
data['MA_20'] = data['Close'].rolling(window=20).mean()
data['RSI'] = talib.RSI(data['Close'], timeperiod=14)
macd, macdsignal, macdhist = talib.MACD(data['Close'], fastperiod=12, slowperiod=26, signalperiod=9)
data['MACD'] = macd
data['MACD_Signal'] = macdsignal
data['MACD_Hist'] = macdhist
data['BB_Middle'] = data['Close'].rolling(window=20).mean()
data['BB_Upper'] = data['BB_Middle'] + 2 * data['Close'].rolling(window=20).std()
data['BB_Lower'] = data['BB_Middle'] - 2 * data['Close'].rolling(window=20).std()
data['OBV'] = talib.OBV(data['Close'], data['Volume'])
data = data.dropna()
data['Target'] = data['Close'].shift(-1)
data['Signal'] = 0
data.loc[(data['MA_5'] > data['MA_10']) & (data['MA_5'].shift(1) <= data['MA_10'].shift(1)), 'Signal'] = 1
data.loc[(data['MA_5'] < data['MA_10']) & (data['MA_5'].shift(1) >= data['MA_10'].shift(1)), 'Signal'] = -1
features = ['Close', 'MA_5', 'MA_10', 'MA_20', 'RSI', 'MACD', 'MACD_Signal', 'OBV', 'Volume']
X = data[features].dropna()
y = data['Target'].dropna()
signal_y = data['Signal'].dropna()
X_train, X_test, y_train, y_test, signal_y_train, signal_y_test = train_test_split(X, y, signal_y, test_size=0.2, random_state=42)

# 模型训练 (股价预测)
model = RandomForestRegressor(n_estimators=args.n_estimators, random_state=42)
model.fit(X_train, y_train)
y_pred = model.predict(X_test)
rmse = np.sqrt(mean_squared_error(y_test, y_pred))
print(f"RMSE: {rmse}")
if run:
    run.log('rmse', rmse)  # 记录指标

# 模型训练 (买卖信号)
signal_model = RandomForestClassifier(n_estimators=args.n_estimators, random_state=42)
signal_model.fit(X_train, signal_y_train)
signal_pred = signal_model.predict(X_test)
accuracy = accuracy_score(signal_y_test, signal_pred)
print(f"Accuracy: {accuracy}")
print(classification_report(signal_y_test, signal_pred))
if run:
    run.log('accuracy', accuracy)  # 记录指标

# 保存模型
os.makedirs('outputs', exist_ok=True)
import joblib
joblib.dump(model, 'outputs/stock_price_model.pkl')
joblib.dump(signal_model, 'outputs/stock_signal_model.pkl')
if run:
    run.upload_file(name='stock_price_model.pkl', path_or_stream='./outputs/stock_price_model.pkl')
    run.upload_file(name='stock_signal_model.pkl', path_or_stream='./outputs/stock_signal_model.pkl')

if run:
    run.complete()
