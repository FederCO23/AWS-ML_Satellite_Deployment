from datetime import datetime
import os

def ID_Gen(file_path):
    
    """Reads, increments, and updates a counter from a file, returning it with this mask: NNNNNN-YYYY-MM-DD """
    
    try:
        # Read the current counter value
        with open(file_path, "r") as file:
            counter = int(file.read())
    except (FileNotFoundError, ValueError):
        # If file doesn't exist or is empty, start from 0
        counter = 0

    # Increment counter
    counter += 1

    # Write updated counter back to file
    with open(file_path, "w") as file:
        file.write(str(counter))

    # current date using YYYY-MM-DD mask
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    return f"{counter:06d}-" + current_date
