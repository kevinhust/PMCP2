# Stock Analysis System

## Overview
This project builds a real-time stock analysis system for Tesla (TSLA) using AWS services and the Yahoo Finance API. It fetches real-time stock data, calculates technical indicators (MA20, MACD), predicts future price movements using a machine learning model, and stores results in DynamoDB.

### Features
- **Real-Time Data**: Fetches TSLA stock data every minute via `yfinance`.
- **Data Processing**: Streams data through Kinesis and processes it in Lambda.
- **Prediction**: Uses a RandomForest model trained on historical data via SageMaker.
- **Storage**: Saves results in DynamoDB with timestamp sorting.

### AWS Services
- **S3**: `kevinw-p2` - Stores historical data and trained model.
- **Kinesis**: `stock-stream` - Streams real-time stock data.
- **DynamoDB**: `stock-table` - Stores stock data with predictions.
- **Lambda**: `StockAnalysisLambda` - Processes data and predicts prices.
- **SageMaker**: `tsla-stock-predictor` - Hosts the ML model.
- **IAM**: `StockAnalysisRole` - Grants permissions to services.

---

## Prerequisites
- **Python 3.9**: Install with required packages.
- **AWS Account**: Configured with sufficient permissions.
- **AWS CLI**: Installed and configured (`aws configure`).

### Required Packages
Install via pip:
```bash
pip install boto3 yfinance pandas TA-Lib scikit-learn sagemaker