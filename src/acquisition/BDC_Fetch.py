

import json
import boto3

import math
import numpy as np
import numpy.ma as ma

from datetime import datetime
import os

from io import BytesIO

import time

import traceback

import pystac_client
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform
from rasterio.windows import from_bounds
from rasterio.mask import mask
from rasterio.windows import Window, transform as window_transform
from rasterio.windows import from_bounds
from geopy.distance import geodesic

# -------------------

# AWS S3 Client
s3 = boto3.client('s3')
#batch_client = boto3.client('batch')
stepfunctions_client = boto3.client('stepfunctions')

# Define S3 bucket configuration
            
S3_BUCKET = "satellite-ml-solarp-detection-data"
COUNTER_FILE = "etc/transaction_counter.txt"

# General variables
sub_image_pixels = 256  # input images' size

def lambda_handler(event, context):
    """
    AWS Lambda function to fetch images from Brazil Data Cube (BDC) and store them in S3.
    It generates a `transaction_id`, processes satellite images, saves them to S3, 
    and triggers a Step Function to continue the workflow.
    """
    start_time = time.time()
    print("Lambda execution started...")

    # Extract parameters from API Gateway request
    transaction_ID = ID_Gen()
    

    try:
        # Extract parameters from the event    
        center_point = event.get('center_point')  # (lat, lon)
        if not center_point or len(center_point) != 2:
            raise ValueError("Invalid or missing 'center_point'. Expected format: [latitude, longitude]")
        center_point = tuple(center_point)  # Ensure it's a tuple

        ns_distance_km = event.get('ns_distance_km', 10)
        we_distance_km = event.get('we_distance_km', 10)
        datetime_range = event.get('datetime_range', '2024-07-01/2024-08-31')

        # Debugging info
        print(f"Fetching images for center: {center_point}, datetime_range: {datetime_range}")

        # Connect to Brazil Data Cube
        api_start = time.time()
        print("Connecting to Brazil Data Cube...")
        service = pystac_client.Client.open("https://data.inpe.br/bdc/stac/v1/")
        print("Connected to BDC in:", time.time() - api_start, "seconds")

        fetch_start = time.time()
        print("Fetching satellite images...")
        collection = service.get_collection("S2-16D-2")

        # Step 1 - Calculate bounding box
        original_bb_north = geodesic(kilometers=ns_distance_km / 2).destination(center_point, 0).latitude
        original_bb_south = geodesic(kilometers=ns_distance_km / 2).destination(center_point, 180).latitude
        original_bb_east = geodesic(kilometers=we_distance_km / 2).destination(center_point, 90).longitude
        original_bb_west = geodesic(kilometers=we_distance_km / 2).destination(center_point, 270).longitude
        bbox = (original_bb_west, original_bb_south, original_bb_east, original_bb_north)

        # Step 2 - Define original bbox
        item_search = service.search(
            bbox=bbox, 
            datetime=datetime_range, 
            collections=["S2-16D-2"]
        )
        
        items_list = list(item_search.items())
        print("Image fetching took:", time.time() - fetch_start, "seconds")


        # Debug Raster Processing
        raster_start = time.time()
        print("Processing raster images...")

        if not items_list:
            return {"statusCode": 404, "body": json.dumps("No images found for the given parameters.")}

        # Extract one image (example with Red band)
        red_data_list, red_transforms, red_crs_list = read_multiple_items(items_list, 'B04', bbox)
        median_red = compute_median_band(red_data_list)
        nodata_value = -9999.0
        median_red_filled = median_red.filled(nodata_value).astype('float32')

        # Step 3 - Determine the correct number of tiles
        full_height, full_width = median_red_filled.shape
        ratio_height = full_height / sub_image_pixels
        ratio_width = full_width / sub_image_pixels

        nb_rows = int(ratio_height) + 1
        nb_cols = int(ratio_width) + 1

        ori_ns_delta_deg = original_bb_north - original_bb_south
        ori_we_delta_deg = original_bb_east - original_bb_west
    
        ns_deg_by_row = ori_ns_delta_deg / ratio_height
        we_deg_by_col = ori_we_delta_deg / ratio_width

        # Step-4 Extend the bounding box area
        extended_bb_north = original_bb_north + ns_deg_by_row/2
        extended_bb_south = original_bb_south - ns_deg_by_row/2
        extended_bb_west = original_bb_west - we_deg_by_col/2
        extended_bb_east = original_bb_east + we_deg_by_col/2
        bbox = (extended_bb_west, extended_bb_south, extended_bb_east, extended_bb_north)

        # Consider four bands: red, green, blue, and NIR
        red_data_list, red_transforms, red_crs_list = read_multiple_items(items_list, 'B04', bbox)
        green_data_list, green_transforms, green_crs_list = read_multiple_items(items_list, 'B03', bbox)
        blue_data_list, blue_transforms, blue_crs_list = read_multiple_items(items_list, 'B02', bbox)
        nir_data_list, nir_transforms, nir_crs_list = read_multiple_items(items_list, 'B08', bbox)
    
        # Compute median band values to absorb cloud distortions
        median_red = compute_median_band(red_data_list)
        median_green = compute_median_band(green_data_list)
        median_blue = compute_median_band(blue_data_list)
        median_nir = compute_median_band(nir_data_list)
    
        # Prepare median bands for writing
        nodata_value = -9999.0
        median_red_filled = median_red.filled(nodata_value).astype('float32')
        median_green_filled = median_green.filled(nodata_value).astype('float32')
        median_blue_filled = median_blue.filled(nodata_value).astype('float32')
        median_nir_filled = median_nir.filled(nodata_value).astype('float32')
        print("Raster processing completed in:", time.time() - raster_start, "seconds")

        # Step 5 - Save sub-images with correct transform
        reference_transform = red_transforms[0]
        reference_crs = red_crs_list[0]

        # Debug Grid images Processing
        grid_start = time.time()
        for j in range(nb_cols):
            rows_start = time.time()
            for i in range(nb_rows):

                # Define slice bounds
                row_start = i * sub_image_pixels
                row_end = row_start + sub_image_pixels
                col_start = j * sub_image_pixels
                col_end = col_start + sub_image_pixels

                # Extract tile
                red_tile = median_red_filled[row_start:row_end, col_start:col_end]
                green_tile = median_green_filled[row_start:row_end, col_start:col_end]
                blue_tile = median_blue_filled[row_start:row_end, col_start:col_end]
                nir_tile = median_nir_filled[row_start:row_end, col_start:col_end]

                # Compute correct transform for this tile
                tile_window = Window(col_start, row_start, sub_image_pixels, sub_image_pixels)
                tile_transform = rasterio.windows.transform(tile_window, reference_transform)

                stacked_tile = np.stack([red_tile, green_tile, blue_tile, nir_tile])

                # Save directly to S3
                s3_key = save_tile_to_s3(S3_BUCKET, transaction_ID, i, j, stacked_tile, reference_crs, tile_transform, nodata_value)
            print(f"Row #{i} images extracted and saved:", time.time() - rows_start, "seconds")
        print(f"Loop (cols {j} and rows{i} finished: ", time.time() - grid_start, "seconds")

        total_duration = time.time() - start_time

        print(f"Lambda completed execution in {total_duration:.2f} seconds.")

        print(f"Images saved to S3 under transaction_id: {transaction_ID}")

        # Prepare input for Step Function
        step_function_input = {
            "transaction_id": transaction_ID
        }

        # Check for duplicate execution
        running_executions = stepfunctions_client.list_executions(
            stateMachineArn="arn:aws:states:us-east-1:864981724706:stateMachine:ImageEnhancementToPrediction",
            statusFilter="RUNNING"
        )

        for execution in running_executions.get("executions", []):
            execution_arn = execution["executionArn"]

            # Get execution details
            execution_details = stepfunctions_client.get_execution_history(
                executionArn=execution_arn,
                maxResults=1
            )

            # Check the first event for transaction_id
            if execution_details["events"]:
                event_input = json.loads(execution_details["events"][0]["executionStartedEventDetails"]["input"])
                if event_input.get("transaction_id") == transaction_ID:
                    print(f"Execution already running for transaction {transaction_ID}. Skipping duplicate trigger.")
                    return {"statusCode": 200, "body": json.dumps({"message": "Execution already in progress."})}

        print(f"No duplicate execution found. Starting Step Function for transaction {transaction_ID}.")

        # Start the Step Function Execution
        print(f"Starting Step Function for transaction: {transaction_ID}")
        response = stepfunctions_client.start_execution(
            stateMachineArn="arn:aws:states:us-east-1:864981724706:stateMachine:ImageEnhancementToPrediction",
            input=json.dumps(step_function_input)
        )

        print(f"Step Function started with executionArn: {response['executionArn']}")

        return {
            "transaction_id": transaction_ID
        }
         
            
    except Exception as e:
        print("Error occurred:", traceback.format_exc())  # Logs the full error
        return {"statusCode": 500, "body": json.dumps(str(e))}

    


def ID_Gen():
    
    """Reads, increments, and updates a counter in S3, returning it in the format: NNNNNN-YYYY-MM-DD"""
    
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=COUNTER_FILE)
        content = obj["Body"].read().decode("utf-8").strip()
        counter = int(content) if content.isdigit() else 0

    except (s3.exceptions.NoSuchKey, ValueError):
        # If file does not exist or is empty, initialize counter at 0
        counter = 0

    # Increment counter
    counter += 1

    # Upload updated counter back to S3
    s3.put_object(Bucket=S3_BUCKET, Key=COUNTER_FILE, Body=str(counter), ContentType="text/plain")

    # Generate transaction ID with the current date
    current_date = datetime.utcnow().strftime("%Y-%m-%d")
    return f"{counter:06d}-{current_date}"



def read_multiple_items(items, band_name, bbox, masked=True, crs=None):
    source_crs = CRS.from_string('EPSG:4326')
    if crs:
        source_crs = CRS.from_string(crs)
    
    data_list = []
    transforms = []
    crs_list = []
    
    for item in items:
        uri = item.assets[band_name].href
        
        # Expects the bounding box has 4 values
        w, s, e, n = bbox
        
        with rasterio.open(uri) as dataset:
            # Transform the bounding box to the dataset's CRS
            xs, ys = transform(source_crs, dataset.crs, [w, e], [s, n])
            # Create a window from the transformed bounds
            window = from_bounds(xs[0], ys[0], xs[1], ys[1], dataset.transform)
            # Read the data within the window
            data = dataset.read(1, window=window, masked=masked)
            # Get the transform for the windowed data
            window_transform = dataset.window_transform(window)
            # Get the CRS of the dataset
            data_crs = dataset.crs
            
            data_list.append(data)
            transforms.append(window_transform)
            crs_list.append(data_crs)
    
    return data_list, transforms, crs_list



# Compute median bands to mitigate the cloud distortion
def compute_median_band(band_data_list):
    data_stack = ma.stack(band_data_list, axis=0)
    median_band = ma.median(data_stack, axis=0)
    return median_band
    


def save_tile_to_s3(bucket, transaction_id, i, j, stacked_tile, crs, transform, nodata_value):
    """
    Saves a single tile as a GeoTIFF directly to S3.
    """
    
    # Define S3 key (file path in S3)
    s3_key = f"acquisition/{transaction_id}/{transaction_id}_{i:03}_{j:03}.tif"

    # Create an in-memory buffer
    buffer = BytesIO()

    # Write the image to the buffer instead of a file
    with rasterio.open(
        buffer,
        'w',
        driver='GTiff',
        height=stacked_tile.shape[1],
        width=stacked_tile.shape[2],
        count=4,  # 4 bands: Red, Green, Blue, NIR
        dtype='float32',
        crs=crs,
        transform=transform,
        nodata=nodata_value
    ) as dst:
        dst.write(stacked_tile)
        dst.set_band_description(1, 'Red')
        dst.set_band_description(2, 'Green')
        dst.set_band_description(3, 'Blue')
        dst.set_band_description(4, 'NIR')

    # Move to the beginning of the buffer before uploading
    buffer.seek(0)

    # Upload to S3
    s3.put_object(Bucket=bucket, Key=s3_key, Body=buffer.getvalue(), ContentType="image/tiff")

    print(f"Uploaded {s3_key} to S3 successfully.")

    return s3_key
