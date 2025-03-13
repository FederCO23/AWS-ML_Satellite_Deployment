from flask import Flask, request, render_template, jsonify
import boto3
import time

app = Flask(__name__)

# AWS Setup
AWS_REGION = "us-east-1"
STEP_FUNCTION_ARN = "arn:aws:states:us-east-1:864981724706:stateMachine:ImageEnhancementToPrediction"
s3 = boto3.client("s3")
stepfunctions = boto3.client("stepfunctions", region_name=AWS_REGION)

S3_BUCKET = "satellite-ml-solarp-detection-data"

# Homepage with a form
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

# Start Step Function
@app.route("/start", methods=["POST"])
def start_workflow():
    data = request.json
    center_point = data["center_point"]
    ns_distance = data["NorthSouth_distance"]
    we_distance = data["WestEast_distance"]

    # Start Step Function Execution
    response = stepfunctions.start_execution(
        stateMachineArn=STEP_FUNCTION_ARN,
        input=f'{{"center_point": "{center_point}", "NorthSouth_distance": {ns_distance}, "WestEast_distance": {we_distance}}}'
    )

    execution_arn = response["executionArn"]
    return jsonify({"message": "Workflow started!", "executionArn": execution_arn})

# Check Step Function Status
@app.route("/status", methods=["POST"])
def check_status():
    execution_arn = request.json["executionArn"]
    response = stepfunctions.describe_execution(executionArn=execution_arn)
    return jsonify({"status": response["status"]})

# Retrieve Final Report
@app.route("/report", methods=["POST"])
def get_report():
    transaction_id = request.json["transaction_id"]
    report_url = f"https://{S3_BUCKET}.s3.amazonaws.com/reports/{transaction_id}/report.html"
    return jsonify({"report_url": report_url})

if __name__ == "__main__":
    app.run(debug=True)
