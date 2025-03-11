import os
import boto3
import rasterio
import numpy as np
from io import BytesIO
from rasterio.io import MemoryFile
from scipy.ndimage import zoom
import argparse
import time
import argparse
import sys


# AWS S3 Setup
s3 = boto3.client("s3")
BUCKET_NAME = "satellite-ml-solarp-detection-data"

# Set scale_factor internally
SCALE_FACTOR = 2

def read_image_s3(s3_key):

    """Reads a GeoTIFF image from S3 into memory."""

    obj = s3.get_object(Bucket=BUCKET_NAME, Key=s3_key)
    with MemoryFile(obj["Body"].read()) as memfile:
        with memfile.open() as dataset:
            image_data = dataset.read()
            metadata = dataset.meta.copy()

    return image_data, metadata



def upscale_image(image_data, metadata, scale_factor):

    """Applies bicubic interpolation to upscale the image."""

    upscaled_data = []
    for band in image_data:
        upscaled_band = zoom(band, scale_factor, order=3)
        upscaled_data.append(upscaled_band)

    # Update metadata
    metadata["height"] = int(metadata["height"] * scale_factor)
    metadata["width"] = int(metadata["width"] * scale_factor)
    metadata["transform"] = metadata["transform"] * rasterio.Affine.scale(1 / scale_factor)

    return np.array(upscaled_data), metadata



def save_image_s3(image_data, metadata, s3_key):

    """Writes processed image back to S3."""

    with MemoryFile() as memfile:
        with memfile.open(**metadata) as dataset:
            dataset.write(image_data)
        buffer = BytesIO(memfile.read())

    s3.put_object(Bucket=BUCKET_NAME, Key=s3_key, Body=buffer.getvalue())
    print(f"Uploaded: {s3_key}")



def process_images():

    """Main function to process images from S3."""

    start_time = time.time()

    # Retrieve transaction_id and scale_factor from environment variables
    transaction_id = os.getenv("TRANSACTION_ID")
    scale_factor = SCALE_FACTOR  # Default = 2

    print(f"Processing Transaction ID: {transaction_id}")

    if not transaction_id:
        print("ERROR: TRANSACTION_ID is missing.")
        return

    print(f"Processing Transaction ID: {transaction_id} with scale factor {scale_factor}")

    s3_folder = f"acquisition/{transaction_id}/"

    # List images from S3
    response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=s3_folder)
    if "Contents" not in response:
        print(f"No images found in S3 path: {s3_folder}")
        return

    for obj in response["Contents"]:
        filename = obj["Key"].split("/")[-1]
        if not filename.endswith(".tif"):
            continue  # Skip non-TIFF files

        print(f"Processing: {filename}")

        # Read image from S3
        image_data, metadata = read_image_s3(obj["Key"])

        # Apply Bicubic Interpolation
        upscaled_image, metadata = upscale_image(image_data, metadata, scale_factor)

        # Upload enhanced image to S3
        output_s3_key = f"image_enhancement/{transaction_id}/{filename}"
        save_image_s3(upscaled_image, metadata, output_s3_key)

    total_time = time.time() - start_time
    print(f"Processing completed in {total_time:.2f} seconds.")



if __name__ == "__main__":
    process_images()

