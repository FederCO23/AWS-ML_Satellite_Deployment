FROM nvidia/cuda:11.8.0-runtime-ubuntu20.04

# Install dependencies
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install boto3 segmentation-models-pytorch rasterio torch torchvision numpy scikit-learn

# Copy prediction script
COPY prediction.py /app/prediction.py
WORKDIR /app

# Set up entrypoint to accept arguments
ENTRYPOINT ["python3", "prediction.py"]

# Default arguments (this allows AWS Batch to pass arguments dynamically)
CMD ["test-transaction"]
