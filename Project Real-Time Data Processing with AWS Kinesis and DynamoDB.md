#### **Project: Real-Time Data Processing with AWS Kinesis and DynamoDB**

#### **Objective:**

Build a real-time data processing pipeline using AWS Kinesis, DynamoDB, and Python to ingest, process, and store real-time data streams.

#### **Steps:**

#### **1. Setup:**

- **AWS Account:** Ensure students have access to an AWS account.
- **Environment:** Set up Python, AWS CLI, and boto3 in the development environment.

#### **2. Data Generation:**

- **Simulate Real-Time Data:**
- Write a Python script to generate data (e.g., sensor readings) at regular intervals.

```
python
Copy code
import random, time, json
def generate_data():
    while True:
        data = {'sensor_id': random.randint(1, 5), 'temperature': random.uniform(20.0, 30.0), 'timestamp': int(time.time())}
        print(json.dumps(data))
        time.sleep(2)
generate_data()
 
```

#### **3. AWS Kinesis Setup:**

- **Create a Kinesis Stream:**
- Set up a new Kinesis data stream in AWS.
- **Send Data to Kinesis:**
- Use boto3 to send generated data to the Kinesis stream.

```
python
Copy code
import boto3, json
kinesis_client = boto3.client('kinesis', region_name='us-east-1')
def send_data(data, stream_name='your-stream'):
    kinesis_client.put_record(StreamName=stream_name, Data=json.dumps(data), PartitionKey='key')
send_data(sample_data)
```

#### **4. Lambda for Data Processing:**

- **Create Lambda Function:**
- Set up a Lambda function to process data from the Kinesis stream.
- **Process and Store Data:**
- Process the data and store it in DynamoDB using boto3.

```
python
Copy code
import boto3, json
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('your-dynamodb-table')
def lambda_handler(event, context):
    for record in event['Records']:
        payload = json.loads(record['kinesis']['data'])
        if payload['temperature'] > 25.0:
            table.put_item(Item=payload)
    return {'statusCode': 200, 'body': 'Processed successfully'}
```

#### **5. DynamoDB Setup:**

- **Create a DynamoDB Table:**
- Define the table structure and primary key in DynamoDB.

#### **6. Automation & Monitoring:**

- **Set Up CloudWatch:**
- Enable logging and monitoring with CloudWatch for Lambda.

#### **7. Optional: Visualization** with Any Data Visualization Tool (Optional):

- **Visualize Data:**
- For instance, connect QuickSight to DynamoDB and create dashboards to visualize processed data.

#### **8. Testing & Submission:**

- **Test the Pipeline:**
- Run the full pipeline from data generation to storage.
- **Submit Code and Report:**
- Provide code, AWS configurations, and a report on the project.

#### **Learning Outcomes:**

- Real-time data processing with AWS Kinesis.
- Serverless computing with AWS Lambda.
- Data storage in DynamoDB.
- Optional: Data visualization with Amazon QuickSight.

This concise project guide helps you build a real-time data processing pipeline using Python and AWS.



**Report Submission Requirements for Project -2**

- Introduction - Describe in your own words the main objectives of this assignment
- Elaborate about the generation of real-time data.
- Explain how data is being sent to the AWS kinesis stream.
- Run your lambda function and show with proper screenshots how it triggers each time data is received.
- Showcase, data storage in DynamoDB especially add the field **TIMESTAMP** to sort the data.
- Finally, how monitoring and error handling is done.



**Note:** Ideally, the presentation should not be more than 10 min long. The presentation PowerPoint should be submitted under Projects --> "**Project -2 Presentation**",



**Plagiarism:**

Plagiarized assignments will receive a zero mark on the assignment and a failing grade on the course. You may also receive a permanent note of plagiarism on your academic record.