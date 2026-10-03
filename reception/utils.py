import os
import base64
from datetime import datetime, date
from werkzeug.utils import secure_filename

def save_webcam_or_uploaded_photo(photo_payload, upload_folder: str) -> str:
    """
    Saves either a base64 dataURL from the front-desk webcam capture
    or a standard uploaded file to the upload folder. Returns relative filename.
    """
    if not photo_payload:
        return None

    from services.private_files import store_photo

    # Check if payload is a base64 string from canvas / webcam
    if isinstance(photo_payload, str) and photo_payload.startswith('data:image'):
        try:
            # Extract header and base64 string
            header, encoded = photo_payload.split(',', 1)
            file_data = base64.b64decode(encoded, validate=True)
            return store_photo(file_data)
        except Exception as e:
            raise ValueError('The webcam photograph is invalid.') from e

    # Check if payload is a werkzeug FileStorage object
    if hasattr(photo_payload, 'filename') and photo_payload.filename:
        try:
            from flask import current_app
            return store_photo(photo_payload.read(current_app.config['MAX_CONTENT_LENGTH'] + 1))
        except Exception as e:
            raise ValueError('Upload a valid JPEG, PNG, or WebP photograph.') from e

    return None

def parse_dob(dob_str: str):
    """
    Parses date string YYYY-MM-DD into a date object.
    """
    if not dob_str:
        return None
    try:
        return datetime.strptime(dob_str.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None
