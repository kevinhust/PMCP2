import yfinance as yf
import pandas as pd
import numpy as np
import talib
import boto3
import sagemaker
import os
import logging
import json
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sagemaker.sklearn import SKLearn
from botocore.exceptions import ClientError

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置
CONFIG = {
    'REGION': os.environ.get('AWS_REGION', 'us-east-1'),
    'BUCKET_NAME': os.environ.get('S3_BUCKET', 'kevinw-p2'),
    'ROLE_NAME': os.environ.get('IAM_ROLE', 'StockAnalysisRole'),
    'ENDPOINT_NAME': os.environ.get('ENDPOINT_NAME', 'tsla-stock-predictor'),
    'STOCK_SYMBOL': os.environ.get('STOCK_SYMBOL', 'TSLA'),
    'INSTANCE_TYPE': os.environ.get('INSTANCE_TYPE', 'ml.m5.large'),
    'INSTANCE_COUNT': int(os.environ.get('INSTANCE_COUNT', '1')),
    'MODEL_PATH': 'model',
    'DATA_PATH': 'data'
}

def prepare_stock_data(symbol: str, period: str = "1y") -> pd.DataFrame:
    """
    获取并准备股票数据
    """
    try:
        logger.info(f"Fetching historical data for {symbol}")
        stock = yf.Ticker(symbol)
        data = stock.history(period=period)
        
        if data.empty:
            raise ValueError(f"No data available for symbol {symbol}")
        
        # 计算技术指标
        data['MA20'] = talib.SMA(data['Close'], timeperiod=20)
        data['MA50'] = talib.SMA(data['Close'], timeperiod=50)
        data['MA200'] = talib.SMA(data['Close'], timeperiod=200)
        data['MACD'], data['Signal'], data['Hist'] = talib.MACD(
            data['Close'], fastperiod=12, slowperiod=26, signalperiod=9
        )
        data['RSI'] = talib.RSI(data['Close'], timeperiod=14)
        
        # 创建目标变量（5天后的价格变动）
        data['Target'] = (data['Close'].shift(-5) > data['Close']).astype(int)
        
        # 删除缺失值
        data = data.dropna()
        
        logger.info(f"Prepared {len(data)} records of stock data")
        return data
    except Exception as e:
        logger.error(f"Error preparing stock data: {str(e)}")
        raise

def save_and_upload_data(data: pd.DataFrame, config: dict) -> str:
    """
    保存数据并上传到S3
    """
    try:
        # 创建本地目录
        os.makedirs(config['DATA_PATH'], exist_ok=True)
        
        # 保存数据
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        local_path = f"{config['DATA_PATH']}/{config['STOCK_SYMBOL']}_{timestamp}.csv"
        data.to_csv(local_path, index=True)
        
        # 上传到S3
        s3_path = f"data/{os.path.basename(local_path)}"
        s3 = boto3.client('s3', region_name=config['REGION'])
        s3.upload_file(local_path, config['BUCKET_NAME'], s3_path)
        
        s3_uri = f"s3://{config['BUCKET_NAME']}/{s3_path}"
        logger.info(f"Data uploaded to {s3_uri}")
        return s3_uri
    except Exception as e:
        logger.error(f"Error saving and uploading data: {str(e)}")
        raise

def create_training_script() -> str:
    """
    创建训练脚本
    """
    script = """
import argparse
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def prepare_features(data):
    feature_columns = [
        'Close', 'Volume', 'MA20', 'MA50', 'MA200',
        'MACD', 'Signal', 'Hist', 'RSI'
    ]
    return data[feature_columns]

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', type=str, required=True)
    parser.add_argument('--model-dir', type=str, required=True)
    args = parser.parse_args()

    # 加载数据
    logger.info("Loading training data")
    data = pd.read_csv(args.train, index_col=0)
    
    # 准备特征和目标
    X = prepare_features(data)
    y = data['Target']
    
    # 训练模型
    logger.info("Training model")
    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42
    )
    model.fit(X, y)
    
    # 评估模型
    y_pred = model.predict(X)
    report = classification_report(y, y_pred)
    logger.info(f"Model Performance:\\n{report}")
    
    # 保存模型
    model_path = f"{args.model_dir}/model.joblib"
    logger.info(f"Saving model to {model_path}")
    joblib.dump(model, model_path)
    
    # 保存特征重要性
    feature_importance = pd.DataFrame({
        'feature': X.columns,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    logger.info("Feature Importance:\\n" + str(feature_importance))
"""
    script_path = f"{CONFIG['MODEL_PATH']}/train.py"
    os.makedirs(CONFIG['MODEL_PATH'], exist_ok=True)
    
    with open(script_path, 'w') as f:
        f.write(script)
    
    return script_path

def train_and_deploy_model(train_script: str, data_uri: str, config: dict) -> None:
    """
    训练并部署模型
    """
    try:
        # 初始化SageMaker会话
        sagemaker_session = sagemaker.Session()
        role = boto3.client('iam').get_role(RoleName=config['ROLE_NAME'])['Role']['Arn']
        
        # 配置训练作业
        sklearn_estimator = SKLearn(
            entry_point=train_script,
            role=role,
            instance_count=config['INSTANCE_COUNT'],
            instance_type=config['INSTANCE_TYPE'],
            framework_version='1.0-1',
            base_job_name=f"{config['STOCK_SYMBOL'].lower()}-training"
        )
        
        # 训练模型
        logger.info("Starting model training")
        sklearn_estimator.fit({'train': data_uri})
        
        # 部署模型
        logger.info(f"Deploying model to endpoint: {config['ENDPOINT_NAME']}")
        predictor = sklearn_estimator.deploy(
            initial_instance_count=1,
            instance_type=config['INSTANCE_TYPE'],
            endpoint_name=config['ENDPOINT_NAME']
        )
        
        logger.info(f"Model successfully deployed to endpoint: {config['ENDPOINT_NAME']}")
        
    except Exception as e:
        logger.error(f"Error in training and deployment: {str(e)}")
        raise

def main():
    try:
        # 准备数据
        data = prepare_stock_data(CONFIG['STOCK_SYMBOL'])
        
        # 保存并上传数据
        data_uri = save_and_upload_data(data, CONFIG)
        
        # 创建训练脚本
        train_script = create_training_script()
        
        # 训练和部署模型
        train_and_deploy_model(train_script, data_uri, CONFIG)
        
    except Exception as e:
        logger.error(f"Pipeline execution failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()