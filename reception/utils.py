import os
import base64
import uuid
from datetime import datetime, date
from werkzeug.utils import secure_filename

def save_webcam_or_uploaded_photo(photo_payload, upload_folder: str) -> str:
    """
    Saves either a base64 dataURL from the front-desk webcam capture
    or a standard uploaded file to the upload folder. Returns relative filename.
    """
    if not photo_payload:
        return None

    os.makedirs(upload_folder, exist_ok=True)
    filename = f"pt_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.jpg"
    target_path = os.path.join(upload_folder, filename)

    # Check if payload is a base64 string from canvas / webcam
    if isinstance(photo_payload, str) and photo_payload.startswith('data:image'):
        try:
            # Extract header and base64 string
            header, encoded = photo_payload.split(',', 1)
            file_data = base64.b64decode(encoded)
            with open(target_path, 'wb') as f:
                f.write(file_data)
            return filename
        except Exception as e:
            print(f"Error decoding base64 photo: {e}")
            return None

    # Check if payload is a werkzeug FileStorage object
    if hasattr(photo_payload, 'filename') and photo_payload.filename:
        try:
            photo_payload.save(target_path)
            return filename
        except Exception as e:
            print(f"Error saving uploaded photo: {e}")
            return None

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
