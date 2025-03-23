#
# This script converts .GEOtiff files with FP predictions into all-black images
# The resulting images will be used to re-train the Model an fine-tune it.
#

import re
import glob
from PIL import Image
import numpy as np
import rasterio

# Function to extract the numeric value from filenames
def numeric_sort_key(filepath):
    # Extract numbers from the filename using a regular expression
    match = re.search(r'\d+', filepath)
    # Return the integer value of the number if found, otherwise 0
    return int(match.group()) if match else 0

folder_label_train = sorted(
    glob.glob("../../../UCSD_MLBootcamp_Capstone/5-Data_Wrangling/data_split2sr_FT/train/labels/target(20??).tif"),
    key=numeric_sort_key
)

folder_label_val = sorted(
    glob.glob("../../../UCSD_MLBootcamp_Capstone/5-Data_Wrangling/data_split2sr_FT/val/labels/target(20??).tif"),
    key=numeric_sort_key
)

folder_label_test = sorted(
    glob.glob("../../../UCSD_MLBootcamp_Capstone/5-Data_Wrangling/data_split2sr_FT/test/labels/target(20??).tif"),
    key=numeric_sort_key
)


if __name__ == '__main__':

    print(f'Number of files to treat:')
    print(f'/ttrain: {len(folder_label_train)}')
    print(f'/tval: {len(folder_label_val)}')
    print(f'/ttest: {len(folder_label_test)}')
    
    
    print(80*'-')
    print(f'first val: {folder_label_val[0]}')
    file = folder_label_val[0]

    folders = [folder_label_train, folder_label_val, folder_label_test]    
    
    for folder in folders:
        nb_of_images = 0
        for file in folder:
            # Open the GeoTIFF in read mode
            with rasterio.open(file) as src:
                profile = src.profile  # Save metadata/profile
                data = src.read()      
                
                # Cancel compression
                profile.pop('compress', None)
                profile['compress'] = 'none'

            # Set all pixel values to zero
            zero_data = np.zeros_like(data)
            
            # Overwrite the file with the same metadata and zeroed data
            with rasterio.open(file, 'w', **profile) as dst:
                dst.write(zero_data)
            
            nb_of_images += 1
        
        print(f'{folder}: {nb_of_images} treated images')
    
    
    