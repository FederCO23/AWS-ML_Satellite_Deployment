from flask import Flask, request, render_template, jsonify
import boto3
import json
import logging

app = Flask(__name__)

# AWS Setup
AWS_REGION = "us-east-1"
STEP_FUNCTION_ARN = "arn:aws:states:us-east-1:864981724706:stateMachine:ImageEnhancementToPrediction"
S3_BUCKET = "satellite-ml-solarp-detection-data"

# Ensure required AWS environment variables are set
if not STEP_FUNCTION_ARN or not S3_BUCKET:
    raise ValueError("Missing required AWS environment variables")

stepfunctions = boto3.client("stepfunctions", region_name=AWS_REGION)

# Configure logging
logging.basicConfig(filename='flask.log', level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())  # Send logs to CloudWatch

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/start", methods=["POST"])
def start_workflow():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid request: No JSON payload received."}), 400
        
        logger.info(f"Received request data: {data}")

        center_point = data.get("center_point")
        ns_distance = data.get("ns_distance_km")
        we_distance = data.get("we_distance_km")

        if not center_point or ns_distance is None or we_distance is None:
            return jsonify({"error": "Missing required parameters: center_point, ns_distance_km, we_distance_km"}), 400

        input_data = {
            "center_point": center_point,
            "ns_distance_km": int(ns_distance),
            "we_distance_km": int(we_distance),
        }

        # Start Step Function Execution
        response = stepfunctions.start_execution(
            stateMachineArn=STEP_FUNCTION_ARN,
            input=json.dumps(input_data)
        )

        execution_arn = response.get("executionArn")
        logger.info(f"Step Function started successfully: {execution_arn}")

        return _corsify_response(jsonify({"message": "Workflow started!", "executionArn": execution_arn}))

    except ValueError:
        logger.error("Invalid data type received")
        return jsonify({"error": "Invalid data type in request payload."}), 400

    except boto3.exceptions.Boto3Error as e:
        logger.error(f"AWS Boto3 Error: {str(e)}")
        return jsonify({"error": f"AWS Error: {str(e)}"}), 500

    except Exception as e:
        logger.error(f"Unexpected Error: {str(e)}")
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500

@app.route("/status", methods=["GET"])
def check_status():
    try:
        execution_arn = request.args.get("executionArn")

        if not execution_arn:
            return jsonify({"error": "Missing executionArn parameter"}), 400

        response = stepfunctions.describe_execution(executionArn=execution_arn)
        status = response["status"]

        # Fetch execution history
        history_response = stepfunctions.get_execution_history(
            executionArn=execution_arn, 
            maxResults=10,  # Get more recent events
            reverseOrder=True  # Get newest events first
        )

        events = history_response.get("events", [])

        # Extract the latest step
        current_step = "Unknown"
        for event in events:
            if "stateEnteredEventDetails" in event:
                current_step = event["stateEnteredEventDetails"]["name"]
                break  # Take the most recent step

        return jsonify({"status": status, "current_step": current_step})

    except Exception as e:
        logger.error(f"Error fetching status: {str(e)}")
        return jsonify({"error": "Failed to retrieve execution status"}), 500


def _corsify_response(response):
    """Adds CORS headers to the response."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

if __name__ == "__main__":
    app.run(debug=True)
