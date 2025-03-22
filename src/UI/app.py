from flask import Flask, request, render_template, jsonify, send_file
import boto3
import json
import logging
import zipfile
import io
import os


app = Flask(__name__, static_folder='static', template_folder='templates')

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

s3_client = boto3.client("s3", region_name=AWS_REGION)


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
            maxResults=10,  # Get the most recent events
            reverseOrder=True  # Get newest events first
        )

        events = history_response.get("events", [])
        
        # Extract the correct step name
        current_step = "Unknown"
        for event in events:
            if "stateEnteredEventDetails" in event and "name" in event["stateEnteredEventDetails"]:
                current_step = event["stateEnteredEventDetails"]["name"]
                break  # Take the most recent step

        # Extract transaction_id from execution output
        transaction_id = None
        if "output" in response:
            try:
                output_data = json.loads(response["output"])
                if "Container" in output_data and "Environment" in output_data["Container"]:
                    for env_var in output_data["Container"]["Environment"]:
                        if env_var["Name"] == "TRANSACTION_ID":
                            transaction_id = env_var["Value"]
                            break
            except json.JSONDecodeError:
                pass  # Ignore JSON errors

        return jsonify({
            "status": status,
            "current_step": current_step,
            "transaction_id": transaction_id  # Now always included
        })

    except Exception as e:
        return jsonify({"error": f"Failed to retrieve execution status: {str(e)}"}), 500



@app.route("/get-report", methods=["GET"])
def get_report():
    transaction_id = request.args.get("transaction_id")
    if not transaction_id:
        logger.error("Transaction ID is missing in the request")
        return jsonify({"error": "Missing transaction_id"}), 400

    # Construct the key for report.html
    report_key = f"reports/{transaction_id}/report.html"

    try:
        # Debug: Log transaction_id and report_key
        logger.info(f"Fetching report for transaction_id: {transaction_id}")
        logger.info(f"Constructed S3 report key: {report_key}")

        # Generate a pre-signed URL for report.html
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": report_key},
            ExpiresIn=3600  # 1-hour expiration
        )

        logger.info(f"Generated pre-signed URL: {presigned_url}")
        return jsonify({"report_url": presigned_url})

    except Exception as e:
        logger.error(f"Error fetching report: {str(e)}")
        return jsonify({"error": str(e)}), 500



@app.route("/download-results", methods=["GET"])
def download_results():
    transaction_id = request.args.get("transaction_id")
    if not transaction_id:
        return jsonify({"error": "Missing transaction_id"}), 400

    # List of files to download
    files = [
        f"reports/{transaction_id}/overlay.png",
        f"reports/{transaction_id}/report.html",
        f"reports/{transaction_id}/input.png",
        f"reports/{transaction_id}/prediction.png"
    ]

    # Create an in-memory ZIP file
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_key in files:
            try:
                obj = s3_client.get_object(Bucket=S3_BUCKET, Key=file_key)
                zip_file.writestr(os.path.basename(file_key), obj["Body"].read())
            except Exception as e:
                logging.error(f"Error adding {file_key} to ZIP: {str(e)}")

    zip_buffer.seek(0)

    #Now we set the filename to transaction_id.zip
    zip_filename = f"{transaction_id}.zip"
    
    # Upload ZIP to S3
    zip_key = f"reports/{transaction_id}/{zip_filename}"
    s3_client.put_object(Bucket=S3_BUCKET, Key=zip_key, Body=zip_buffer.getvalue(), ContentType="application/zip")

    # Generate a pre-signed URL
    presigned_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": zip_key},
        ExpiresIn=3600  # 1-hour expiry
    )

    return jsonify({"download_url": presigned_url})



def _corsify_response(response):
    """Adds CORS headers to the response."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

if __name__ == "__main__":
    app.run(debug=True)
