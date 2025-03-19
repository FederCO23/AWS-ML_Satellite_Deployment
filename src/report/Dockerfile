# Use an official Python runtime as a base image
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Install required system dependencies (for OpenCV, image processing, and GeoTIFF)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    boto3 \
    numpy \
    pandas \
    opencv-python-headless \
    matplotlib \
    imageio \
    rasterio

# Copy the report script into the container
COPY report.py .

# Set the entrypoint to run the script
ENTRYPOINT ["python", "report.py"]
