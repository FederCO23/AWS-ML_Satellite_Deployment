# Base image with Python 3.11
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    gdal-bin \
    libgdal-dev \
    libproj-dev \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for GDAL and PROJ
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Install Python dependencies
RUN pip install --no-cache-dir numpy scipy rasterio boto3

# Copy the Python script into the container
COPY Image_Enhancement.py /app/

# Define the entrypoint (default execution)
ENTRYPOINT ["python", "/app/Image_Enhancement.py"]

