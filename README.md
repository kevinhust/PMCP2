# Real-time Stock Analysis System

This project implements a real-time stock analysis system based on AWS, using Kinesis for data stream processing, DynamoDB for data storage, and SageMaker for machine learning predictions.

## System Architecture

```
[Data Source] -> [Kinesis] -> [Lambda] -> [DynamoDB]
                               |
                         [SageMaker] -> [Predictions]
```

## Features

- Real-time stock data collection and processing
- Technical indicator calculations (MA, MACD, RSI, etc.)
- Machine learning model training and prediction
- Scalable data storage and processing
- Complete error handling and logging
- AWS service configuration based on best practices

## Prerequisites

- Python 3.9+
- AWS account and configured credentials
- TA-Lib (Technical Analysis Library)

## Installation

1. Clone repository:
```bash
git clone <repository-url>
cd stock-analysis-system
```

2. Create and activate virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
Create a `.env` file and set the following variables:
```
AWS_REGION=us-east-1
S3_BUCKET=your-bucket-name
KINESIS_STREAM=stock-stream
DYNAMODB_TABLE=stock-table
STOCK_SYMBOL=TSLA
SAGEMAKER_ENDPOINT=tsla-stock-predictor
```

## Deployment

1. Deploy AWS services:
```bash
chmod +x deploy_aws_services.sh
./deploy_aws_services.sh
```

2. Prepare and train model:
```bash
python prepare_and_train_sagemaker.py
```

3. Start data collection:
```bash
python push_to_kinesis.py
```

## Project Structure

```
.
├── README.md                       # Project documentation
├── requirements.txt                # Project dependencies
├── deploy_aws_services.sh          # AWS services deployment script
├── push_to_kinesis.py             # Data collection script
├── prepare_and_train_sagemaker.py # Model training script
└── lambda_function.py             # Lambda processing function
```

## Configuration

### AWS Service Configuration

- **S3**: For storing training data and models
- **Kinesis**: Real-time data stream processing
- **DynamoDB**: Data persistence storage
- **Lambda**: Real-time data processing
- **SageMaker**: Model training and deployment

### Security Configuration

- Use IAM roles for minimum privilege access control
- Enable server-side encryption
- Implement error handling and retry mechanisms
- Support resource tag management

## Monitoring and Logging

- CloudWatch logs integration
- Custom metrics and alerts
- Detailed application logging

## Development Guide

### Adding New Technical Indicators

1. Add new indicators in the `calculate_indicators` function in `lambda_function.py`
2. Update feature engineering in `prepare_and_train_sagemaker.py`
3. Retrain the model

### Customizing the Model

1. Modify the training script in `prepare_and_train_sagemaker.py`
2. Adjust model parameters and features
3. Redeploy the model

## Troubleshooting

### Common Issues

1. **Data Collection Failure**
   - Check API limits and quotas
   - Verify network connection
   - Check CloudWatch logs

2. **Model Training Failure**
   - Check data format
   - Verify IAM permissions
   - Check SageMaker training logs

3. **Lambda Function Timeout**
   - Increase timeout settings
   - Optimize code performance
   - Consider batch processing

## Maintenance and Updates

- Regularly update dependencies
- Monitor AWS service usage
- Backup important data
- Check and optimize costs

## License

MIT License

## Contributing Guide

1. Fork the project
2. Create a feature branch
3. Submit changes
4. Push to the branch
5. Create Pull Request

## Contact

For questions or suggestions, please create an Issue or contact the project maintainer.