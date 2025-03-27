import boto3
import re
from datetime import datetime, timedelta
import argparse

# === CONFIGURATION ===
bucket_name = "satellite-ml-solarp-detection-data"
base_folders = ['acquisition/', 'image_enhancement/', 'predictions/', 'reports/']
#days_to_keep = 30  # Keep last 30 days
#cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

# === INIT S3 CLIENT ===
s3 = boto3.client('s3')

# === REGEX TO MATCH SUBFOLDER ===
pattern = re.compile(r'(\d{6})-(\d{4}-\d{2}-\d{2})/')

# === FUNCTION TO DELETE OLD OBJECTS ===
def delete_old_subfolders(target_date):

    seen_folder = set()

    for base in base_folders:
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket_name, Prefix=base):
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                key = obj['Key']
                print(f"Checking: {key}")
                match = pattern.search(key)
                if match:
                    folder_date_str = match.group(2)
                    try:
                        folder_date = datetime.strptime(folder_date_str, '%Y-%m-%d').date()
                        if folder_date == target_date:
                            prefix_to_delete = key.split(match.group(0))[0] + match.group(0)
                            if prefix_to_delete not in seen_folder:
                                print(f'Deleting folder: {prefix_to_delete}')
                                delete_prefix(prefix_to_delete)
                                seen_folder.add(prefix_to_delete)
                    except ValueError:
                        print(f'Skipping malformed date in: {folder_date_ster}')
                        continue

# === DELETE ALL OBJECTS UNDER A PREFIX ===
def delete_prefix(prefix):
    print(f'Fetching objects under: {prefix}')
    objects_to_delete = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
    if 'Contents' in objects_to_delete:
        for obj in objects_to_delete['Contents']:
            print(f' - Deleting {obj["Key"]}')
            s3.delete_object(Bucket=bucket_name, Key=obj['Key'])
    else:
        print(f"Nothing found under {prefix} to delete.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clean up old transaction folders in s3.')
    parser.add_argument('--date', required=True, help='Transaction date. Mask: "YYYY-MM-DD"')

    args = parser.parse_args()

    try:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        delete_old_subfolders(target_date)

    except ValueError:
        print("Invalid date format. Please use YYYY-MM-DD.")
