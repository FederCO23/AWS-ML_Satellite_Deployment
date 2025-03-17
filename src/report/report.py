import os
import re
import io
import numpy as np
import pandas as pd
import boto3
import cv2
import rasterio
import imageio.v2 as imageio
import matplotlib.pyplot as plt

# AWS S3 Setup
s3 = boto3.client("s3")
S3_BUCKET = "satellite-ml-solarp-detection-data"

# Retrieve Transaction ID
TRANSACTION_ID = os.getenv("TRANSACTION_ID")
if not TRANSACTION_ID:
    raise ValueError("TRANSACTION_ID environment variable is not set.")

# Define S3 Paths
input_s3_folder = f"image_enhancement/{TRANSACTION_ID}/"
prediction_s3_folder = f"predictions/{TRANSACTION_ID}/"
report_s3_folder = f"reports/{TRANSACTION_ID}/"

# Function to extract row and column from filename
def extract_row_col(filepath):
    match = re.findall(r'(\d+)', os.path.basename(filepath))
    return (int(match[1]), int(match[2])) if len(match) >= 3 else (9999, 9999)

# Function to list S3 files
def list_s3_files(bucket, prefix):
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    if "Contents" not in response:
        raise FileNotFoundError(f"No files found in S3 path: {prefix}")
    return sorted(
        [obj["Key"] for obj in response["Contents"] if obj["Key"].endswith(".tif")],
        key=extract_row_col
    )

# Fetch input and prediction image keys from S3
input_images = list_s3_files(S3_BUCKET, input_s3_folder)
prediction_images = list_s3_files(S3_BUCKET, prediction_s3_folder)

# Determine grid size
nb_of_rows = int(input_images[-1][-11:-8]) + 1
nb_of_cols = int(input_images[-1][-7:-4]) + 1
print(f"Grid shape: {nb_of_rows} rows x {nb_of_cols} cols.")

# Read images from S3
def read_image_s3(s3_key, to_rgb=True):
    obj = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
    img_bytes = io.BytesIO(obj["Body"].read())
    
    with rasterio.open(img_bytes) as src:
        img = src.read().astype(np.float32)
        print(f"Successfully read {s3_key} (bands: {img.shape[0]}, shape: {img.shape[1:]})")
        
        if to_rgb and img.shape[0] == 4:
            img = img[:3]
        elif img.shape[0] == 1:
            img = img[0]
        
        if len(img.shape) == 3:
            img = np.moveaxis(img, 0, -1)
        
        return img

# Normalize images as a group
def normalize_images_group(images):
    min_val = np.min([np.min(img) for img in images])
    max_val = np.max([np.max(img) for img in images])
    
    def normalize(img):
        if max_val == min_val:
            return np.zeros_like(img, dtype=np.uint8)
        return ((img - min_val) / (max_val - min_val) * 255).astype(np.uint8)
    
    return [normalize(img) for img in images]

# Create mosaics
def create_mosaic(image_keys, title, normalize=True):

    images = [read_image_s3(key) for key in image_keys]

    if title == "input":
        if normalize:
            images = normalize_images_group(images)

    elif title == "prediction":
        images = [(img > 0).astype(np.uint8) * 255 for img in images]

    mosaic = np.vstack([
        np.hstack(images[i * nb_of_cols:(i + 1) * nb_of_cols])
        for i in range(nb_of_rows)
    ])
    
    mosaic = mosaic.astype(np.uint8)
    
    # Save the mosaic
    mosaic_key = f"{report_s3_folder}{title}.png"
    image_bytes = io.BytesIO()
    imageio.imwrite(image_bytes, mosaic, format="png")
    s3.put_object(Bucket=S3_BUCKET, Key=mosaic_key, Body=image_bytes.getvalue())
    print(f"Saved mosaic: {mosaic_key}")
    
    return mosaic_key

# Generate mosaics
input_mosaic_key = create_mosaic(input_images, "input")
prediction_mosaic_key = create_mosaic(prediction_images, "prediction", normalize=False)

# Overlay predictions with grid and quadrant numbering
def overlay_prediction_with_grid(input_key, prediction_key, output_key, grid_shape, overlay_color=(0, 255, 255), grid_color=(255, 255, 255), thickness=1):
    """Overlay prediction mask and grid on the input image."""
    
    input_img = read_image_s3(input_key, to_rgb=True)
    pred_mask = read_image_s3(prediction_key, to_rgb=False)

    if input_img is None or pred_mask is None:
        print(f"Skipping overlay due to missing image: {input_key} or {prediction_key}")
        return

    # Convert prediction mask (0 → 0, 1 → 255)
    pred_mask = (pred_mask > 0).astype(np.uint8) * 255
    pred_mask = np.stack([pred_mask] * 3, axis=-1)

    # Overlay detected areas in magenta
    overlay = input_img.copy()
    overlay[pred_mask[:, :, 0] > 0] = overlay_color

    # Add grid and numbering
    overlay = overlay_grid_with_numbers(overlay, grid_shape, grid_color, thickness)

    overlay = overlay.astype(np.uint8)

    # Save the overlay image
    image_bytes = io.BytesIO()
    imageio.imwrite(image_bytes, overlay, format="png")
    s3.put_object(Bucket=S3_BUCKET, Key=output_key, Body=image_bytes.getvalue())
    print(f"Saved final overlay: {output_key}")

# Overlay grid and numbers
def overlay_grid_with_numbers(image, grid_shape, grid_color=(255, 255, 255), thickness=1):
    h, w, _ = image.shape
    grid_h, grid_w = h // grid_shape[0], w // grid_shape[1]
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    font_thickness = 1

    cell_number = 1

    for i in range(grid_shape[0]):
        for j in range(grid_shape[1]):
            x_top_left = j * grid_w + 5
            y_top_left = i * grid_h + 15

            cv2.putText(
                image, 
                str(cell_number), 
                (x_top_left, y_top_left), 
                font, font_scale, grid_color, 
                font_thickness, cv2.LINE_AA
            )
            cell_number += 1
    step = 10
    for i in range(1, grid_shape[0]):
        for x in range(0, w, step * 2):
            cv2.line(image, (x, i * grid_h), (x + step, i * grid_h), grid_color, thickness)
    for j in range(1, grid_shape[1]):
        for y in range(0, h, step * 2):
            cv2.line(image, (j * grid_w, y), (j * grid_w, y + step), grid_color, thickness)

    return image

overlay_key = f"{report_s3_folder}overlay.png"
overlay_prediction_with_grid(input_mosaic_key, prediction_mosaic_key, overlay_key, (nb_of_rows, nb_of_cols))

# Compute statistics
def compute_statistics(prediction_keys, sub_image_shape, scale=5):
    total_pixels, positive_pixels = 0, 0
    stats = []
    
    for i, key in enumerate(prediction_keys):
        pred_img = read_image_s3(key)
        cell_pixels = pred_img.size
        cell_positives = np.sum(pred_img > 0)
        total_pixels += cell_pixels
        positive_pixels += cell_positives
        cell_area = cell_pixels * scale * scale * 10**-6
        positive_area = cell_positives * scale * scale
        
        stats.append({
            "Cell": i + 1,
            "Total Pixels": f"{cell_pixels:,}",
            "Total Area (km^2)": f"{cell_area:,.3f}",
            "Positive Pixels": f"{cell_positives:,}",
            "Positive Area (m^2)": f"{positive_area:,}",
            "Coverage %": (cell_positives / cell_pixels) * 100
        })
    
    ns_extension = f"{nb_of_rows * sub_image_shape[0] * scale:,} m"
    we_extension = f"{nb_of_cols * sub_image_shape[1] * scale:,} m"
    
    return pd.DataFrame(stats), ns_extension, we_extension

stats_df, ns_extension, we_extension = compute_statistics(prediction_images, (512, 512))

# Generate HTML Report
html_content = f"""
<html>
<head><title>Satellite Report {TRANSACTION_ID}</title></head>
<body>
<h2>Satellite Report for {TRANSACTION_ID}</h2>
<h3>Satellite imagery and detection mosaic overlay</h3>
<img src='overlay.png' width='800'>
<h3>Statistics</h3>
{stats_df.to_html(index=False)}
</body>
</html>
"""

# Save HTML report to S3
html_bytes = io.BytesIO(html_content.encode("utf-8"))
s3.put_object(Bucket=S3_BUCKET, Key=f"{report_s3_folder}report.html", Body=html_bytes.getvalue())
print(f"Report generated successfully: {report_s3_folder}report.html")
