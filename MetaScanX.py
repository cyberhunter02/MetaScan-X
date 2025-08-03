import os
import json
import subprocess
import shutil
import base64
import io
import datetime
import hashlib
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from PIL import Image
from weasyprint import HTML

# --- Flask App Initialization ---
app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
DOWNLOAD_FOLDER = 'downloads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['DOWNLOAD_FOLDER'] = DOWNLOAD_FOLDER
app.config['TOOL_NAME'] = "MetaScanX"

def get_thumbnail(image_path: str) -> str | None:
    """Generates a base64 encoded thumbnail of the image."""
    try:
        with Image.open(image_path) as img:
            img.thumbnail((400, 400))
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG")
            return base64.b64encode(buffered.getvalue()).decode()
    except Exception:
        return None

def extract_metadata(image_path: str) -> dict:
    """Extracts metadata from an image using ExifTool."""
    try:
        command = ["exiftool", "-json", "-G", image_path]
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        metadata_list = json.loads(result.stdout)
        if not metadata_list:
            return {"Error": "No metadata found in file."}
        metadata = metadata_list[0]
        cleaned_metadata = {}
        for key, value in metadata.items():
            if ':' in key:
                cleaned_metadata[key.replace(':', '_', 1)] = value
            else:
                cleaned_metadata[f"File_{key}"] = value
        return cleaned_metadata
    except FileNotFoundError:
        return {"Error": "ExifTool not found."}
    except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError) as e:
        return {"Error": f"Metadata extraction failed: {e}"}

def convert_gps_to_decimal(metadata: dict) -> str:
    """Converts GPS data from metadata to a decimal format."""
    try:
        lat_val_str, lon_val_str = metadata.get("EXIF_GPSLatitude"), metadata.get("EXIF_GPSLongitude")
        lat_ref, lon_ref = metadata.get("EXIF_GPSLatitudeRef", "N"), metadata.get("EXIF_GPSLongitudeRef", "E")
        if not lat_val_str or not lon_val_str: return "Not Available"
        def to_decimal(coord_str: str, ref: str) -> float:
            parts = coord_str.replace(' deg ', ' ').replace("'", ' ').replace('"', '').split()
            decimal = float(parts[0]) + (float(parts[1]) / 60.0) + (float(parts[2]) / 3600.0)
            return -decimal if ref in ['S', 'W'] else decimal
        return f"{to_decimal(lat_val_str, lat_ref):.6f}, {to_decimal(lon_val_str, lon_ref):.6f}"
    except:
        return "Not Available"

def calculate_hashes(file_path: str) -> dict:
    """Calculates MD5 and SHA256 hashes for a given file."""
    md5_hash = hashlib.md5()
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
                sha256_hash.update(chunk)
        return {
            "MD5": md5_hash.hexdigest(),
            "SHA256": sha256_hash.hexdigest()
        }
    except Exception as e:
        return {"Error": f"Hash calculation failed: {e}"}

@app.route('/')
def index():
    """Renders the main page."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file_route():
    """Handles file uploads, extracts metadata, and generates a PDF report."""
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({"success": False, "message": "No file selected."}), 400

    file = request.files['file']
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    metadata = extract_metadata(file_path)
    if "Error" in metadata:
        os.remove(file_path)
        return jsonify({"success": False, "message": metadata["Error"]}), 500

    metadata['GPS_Coordinates'] = convert_gps_to_decimal(metadata)
    
    # Calculate and add hash values
    hashes = calculate_hashes(file_path)
    if "Error" in hashes:
        os.remove(file_path)
        return jsonify({"success": False, "message": hashes["Error"]}), 500
    metadata.update({f"Hash_{key}": value for key, value in hashes.items()})

    thumbnail_data = get_thumbnail(file_path)
    
    # Get case details from form
    investigator_name = request.form.get('investigatorName', 'N/A')
    case_id = request.form.get('caseId', 'N/A')
    description = request.form.get('description', 'N/A')

    metadata_groups = {}
    for key, value in metadata.items():
        group, field = key.split('_', 1) if '_' in key else ('Other', key)
        if group not in metadata_groups: metadata_groups[group] = {}
        metadata_groups[group][field] = value
        
    # Re-grouping for better display in the report and web UI
    file_details_group = {
        'File Name': filename,
        'File Size': metadata_groups.get('File', {}).get('FileSize', 'N/A'),
        'File Type': metadata_groups.get('File', {}).get('FileType', 'N/A'),
        'MIME Type': metadata_groups.get('File', {}).get('MIMEType', 'N/A'),
        'MD5': hashes.get('MD5'),
        'SHA256': hashes.get('SHA256'),
        'GPS Coordinates': metadata_groups.get('GPS', {}).get('Coordinates', 'N/A')
    }

    html_content = render_template('report.html',
        filename=filename,
        metadata_groups=metadata_groups,
        thumbnail_data=thumbnail_data,
        report_date=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        investigator_name=investigator_name,
        case_id=case_id,
        description=description,
        file_details=file_details_group
    )
    pdf_filename = os.path.splitext(filename)[0] + "_report.pdf"
    pdf_path = os.path.join(app.config['DOWNLOAD_FOLDER'], pdf_filename)
    HTML(string=html_content).write_pdf(pdf_path)

    os.remove(file_path)

    return jsonify({
        "success": True,
        "filename": filename,
        "thumbnail": thumbnail_data,
        "pdf_report": pdf_filename,
        "metadata_groups": metadata_groups,
        "file_details": file_details_group # Pass this back to the front-end
    })

@app.route('/download/<filename>')
def download_report(filename):
    return send_file(os.path.join(app.config['DOWNLOAD_FOLDER'], filename), as_attachment=True)

if __name__ == '__main__':
    for folder in [UPLOAD_FOLDER, DOWNLOAD_FOLDER]:
        if os.path.exists(folder): shutil.rmtree(folder)
        os.makedirs(folder)
    app.run(debug=True, host='0.0.0.0')
