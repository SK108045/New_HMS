"""Validated patient uploads outside the public web root."""
import io
import os
import uuid
from pathlib import Path

from flask import current_app
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

IMAGE_TYPES = {'JPEG': ('.jpg', 'image/jpeg'), 'PNG': ('.png', 'image/png'),
               'WEBP': ('.webp', 'image/webp')}


def _validated_image(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in IMAGE_TYPES or image.width * image.height > 25_000_000:
                raise ValueError('Choose a JPEG, PNG, or WebP image smaller than 25 megapixels.')
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            output = io.BytesIO()
            # Re-encode to strip active content, trailing bytes and identifying EXIF metadata.
            image.convert('RGB').save(output, format='JPEG', quality=90)
        return output.getvalue(), '.jpg', 'image/jpeg'
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('The uploaded image is invalid.') from exc


def _write(data, category, extension):
    folder = Path(current_app.config['PRIVATE_UPLOAD_FOLDER']) / category
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    filename = uuid.uuid4().hex + extension
    destination = folder / filename
    with destination.open('xb') as handle:
        handle.write(data)
    os.chmod(destination, 0o600)
    return f'{category}/{filename}'


def store_document(file):
    """Return ClinicalDocument attachment fields or raise ValueError."""
    original = secure_filename(file.filename or '')
    if not original:
        raise ValueError('Select a file to upload.')
    data = file.read(current_app.config['MAX_CONTENT_LENGTH'] + 1)
    if not data or len(data) > current_app.config['MAX_CONTENT_LENGTH']:
        raise ValueError('The attachment is empty or exceeds the upload limit.')
    extension = Path(original).suffix.lower()
    if extension == '.pdf':
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-4096:]:
            raise ValueError('The uploaded PDF is invalid.')
        mime = 'application/pdf'
    elif extension in {'.jpg', '.jpeg', '.png', '.webp'}:
        data, extension, mime = _validated_image(data)
    else:
        raise ValueError('Attachments must be PDF, JPEG, PNG, or WebP files.')
    return {'file_path': _write(data, 'documents', extension),
            'file_name': original, 'file_size': len(data), 'mime_type': mime}


def store_photo(data):
    if not data or len(data) > current_app.config['MAX_CONTENT_LENGTH']:
        raise ValueError('The photograph is empty or exceeds the upload limit.')
    data, extension, _ = _validated_image(data)
    return Path(_write(data, 'photos', extension)).name


def private_path(relative_path):
    """Resolve a private path, including a protected legacy attachment."""
    relative = Path(relative_path)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid attachment path.')
    if relative.parts[:2] in {('uploads', 'documents'), ('uploads', 'photos')}:
        category = relative.parts[1]
        private_root = Path(current_app.config['PRIVATE_UPLOAD_FOLDER']).resolve()
        candidate = (private_root / category / relative.name).resolve()
        if not candidate.is_relative_to(private_root):
            raise ValueError('Invalid private attachment path.')
        if candidate.is_file():
            return candidate
        root = Path(current_app.root_path) / 'static' / 'uploads'
        legacy = (Path(current_app.root_path) / 'static' / relative).resolve()
        if not legacy.is_relative_to(root.resolve()):
            raise ValueError('Invalid legacy attachment path.')
        return legacy
    root = Path(current_app.config['PRIVATE_UPLOAD_FOLDER']).resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError('Invalid attachment path.')
    return candidate
