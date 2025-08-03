#!/bin/bash

# Check if virtual environment exists
if [ ! -d "venv" ]; then
  echo "Virtual environment not found. Creating it now..."
  python3 -m venv venv
fi

# Activate the virtual environment
source venv/bin/activate

# Check if required packages are installed
# (You can add more packages here if needed)
if ! pip show Flask &> /dev/null; then
    echo "Installing Flask and other dependencies..."
    pip install Flask Pillow fpdf
fi

# Run the main Python script
echo "Starting the Flask app..."
python3 MetaScanX.py

# Note: 'deactivate' is not needed in this script, as it will deactivate automatically when the script finishes.
