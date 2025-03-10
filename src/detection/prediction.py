import os
import torch
import boto3
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from segmentation_models_pytorch import Unet
import argparse
import re
import io
from sklearn.preprocessing import MinMaxScaler

# AWS S3 Setup
s3 = boto3.client("s3")
BUCKET_NAME = "satellite-ml-solarp-detection-data"

# Model Setup
ENCODER = 'efficientnet-b7'
CLASSES = ['solar_panel']
ACTIVATION = 'sigmoid'
THRESHOLD = 0.5  # Adjust threshold if needed

# Set device
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Load Model
model = Unet(
    in_channels=4,  # Using 4 bands (RGB + NIR)
    encoder_name=ENCODER,
    encoder_weights=None,
    classes=len(CLASSES),
    activation=ACTIVATION,
)
model = model.to(device)

# Load model weights from S3
weights_key = "etc/models/weights/u-net_efficientnet-b7_vBiC_intx2/unet-seed23_wDA&Int_weights.pth"
weights_obj = s3.get_object(Bucket=BUCKET_NAME, Key=weights_key)
weights_data = io.BytesIO(weights_obj['Body'].read())
model.load_state_dict(torch.load(weights_data, map_location=device))
model.eval()
print("Model loaded successfully.")

# Function to read image from S3
def read_image_s3(s3_key):

    obj = s3.get_object(Bucket=BUCKET_NAME, Key=s3_key)
    with MemoryFile(obj["Body"].read()) as memfile:
        with memfile.open() as dataset:
            image_data = dataset.read().astype(np.float32)
            metadata = dataset.meta.copy()

            # Normalize dynamically per image
            #min_vals = image_data.min(axis=(1,2), keepdims=True)
            #max_vals = image_data.max(axis=(1,2), keepdims=True)

            #image_data = (image_data - min_vals) / (max_vals - min_vals + 1e-8)
            #image_data = np.clip(image_data, 0, 1)

            # Reshape image to apply MinMaxScaler
            for band in range(image_data.shape[0]):
                min_val = image_data[band].min()
                max_val = image_data[band].max()
                if max_val > min_val:
                    image_data[band] = (image_data[band] - min_val) / (max_val - min_val)

          
    print(f"Raw Image Shape Before Tensor Conversion: {image_data.shape}")  # Debug print

    return image_data, metadata



# Function to save prediction to S3
def save_prediction_s3(pred_mask, metadata, s3_key):
    
    metadata.update(
        dtype=rasterio.float32,
        count=1,
        compress="lzw"
    )

    with MemoryFile() as memfile:
        with memfile.open(**metadata) as dataset:
            dataset.write(pred_mask, 1)
        buffer = memfile.read()

    s3.put_object(Bucket=BUCKET_NAME, Key=s3_key, Body=buffer)
    print(f"Saved Prediction: {s3_key}")



# Function to sort files numerically
def numeric_sort_key(filepath):

    match = re.search(r'\d+', filepath)
    return int(match.group()) if match else 0



# Main Processing Function
def process_images(transaction_id):

    print(f"Processing Prediction for Transaction ID: {transaction_id}")

    input_s3_folder = f"image_enhancement/{transaction_id}/"
    output_s3_folder = f"predictions/{transaction_id}/"

    # List images from S3
    response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=input_s3_folder)
    if "Contents" not in response:
        print(f"No images found in S3 path: {input_s3_folder}")
        return

    image_keys = sorted(
        [obj["Key"] for obj in response["Contents"] if obj["Key"].endswith(".tif")],
        key=numeric_sort_key
    )

    with torch.no_grad():
        for s3_key in image_keys:
            # Read image from S3
            image_data, metadata = read_image_s3(s3_key)

            # Convert to tensor
            image_tensor = torch.tensor(image_data, dtype=torch.float32).unsqueeze(0).to(device)
            print(f"Image Tensor Shape Before Model: {image_tensor.shape}")  # Debug print

            expected_height = (image_tensor.shape[2] % 32 == 0)
            expected_width = (image_tensor.shape[3] % 32 == 0)

            if not expected_height or not expected_width:
                print(f"Warning: Model input shape is not divisible by 32! Shape = {image_tensor.shape}")

            # Run inference
            prediction = model(image_tensor)

            # Debug: Print stats BEFORE thresholding
            print(f"\nPrediction Stats BEFORE Thresholding (Range: {prediction.min().item()} to {prediction.max().item()})")
            print(f"Unique values (before thresholding): {torch.unique(prediction)}")

            prediction = (prediction > THRESHOLD).int().cpu().numpy().astype(np.float32)

            # Debug: Print stats AFTER thresholding
            print(f"\nPrediction Stats AFTER Thresholding (Range: {prediction.min()} to {prediction.max()})")
            print(f"Unique values (after thresholding): {np.unique(prediction)}")

            # Save to S3
            output_s3_key = output_s3_folder + os.path.basename(s3_key)
            save_prediction_s3(prediction.squeeze(), metadata, output_s3_key)

    print(f"Processing completed for {transaction_id}.")

# Command-line arguments
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prediction Job for AWS Batch")
    parser.add_argument("transaction_id", type=str, help="Transaction ID for prediction")
    args = parser.parse_args()
    process_images(args.transaction_id)
