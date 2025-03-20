import yfinance as yf
import pandas as pd
import talib
import boto3
import sagemaker
from sagemaker.sklearn import SKLearn

# Fetch and prepare historical data
stock = yf.Ticker("TSLA")
data = stock.history(period="1y")
data['MA20'] = talib.SMA(data['Close'], timeperiod=20)
data['MACD'], data['Signal'], _ = talib.MACD(data['Close'], fastperiod=12, slowperiod=26, signalperiod=9)
data['Target'] = (data['Close'].shift(-5) > data['Close']).astype(int)
data = data.dropna()
data.to_csv('tsla_history.csv', index=False)

# Upload to S3
s3 = boto3.client('s3')
s3.upload_file('tsla_history.csv', 'kevinw-p2', 'tsla_history.csv')

# Initialize SageMaker session
sagemaker_session = sagemaker.Session()
role = boto3.client('iam').get_role(RoleName='StockAnalysisRole')['Role']['Arn']

# Define training script
train_script = """
import argparse
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', type=str)
    args = parser.parse_args()

    data = pd.read_csv(args.train)
    X = data[['Close', 'Volume', 'MA20', 'MACD', 'Signal']]
    y = data['Target']

    model = RandomForestClassifier(n_estimators=100)
    model.fit(X, y)
    joblib.dump(model, 'model.joblib')
"""
with open('train.py', 'w') as f:
    f.write(train_script)

# Train model
sklearn_estimator = SKLearn(
    entry_point='train.py',
    role=role,
    instance_count=1,
    instance_type='ml.m5.large',
    framework_version='1.0-1'
)
sklearn_estimator.fit({'train': 's3://kevinw-p2/tsla_history.csv'})

# Deploy model
predictor = sklearn_estimator.deploy(
    initial_instance_count=1,
    instance_type='ml.m5.large',
    endpoint_name='tsla-stock-predictor'
)
print("SageMaker model trained and deployed as 'tsla-stock-predictor'")