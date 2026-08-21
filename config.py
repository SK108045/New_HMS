import os
import secrets

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_urlsafe(32)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 
        f"sqlite:///{os.path.join(BASE_DIR, 'hms.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEMO_LOGIN_ENABLED = os.environ.get('HMS_ENABLE_DEMO_LOGIN', '').lower() == 'true'
    
    # Upload settings
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'photos')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    
    # Facility information for printables & headers
    FACILITY_NAME = "Apex Regional Medical Center"
    FACILITY_CODE = "HSP-2026"
    FACILITY_ADDRESS = "Hospital Road, Medical District, P.O. Box 40100"
    FACILITY_PHONE = "+254 (0) 20 555 0190 / +254 700 000 100"
    FACILITY_EMAIL = "reception@apexmedical.org"
    FACILITY_TAX_PIN = "P051298471Z"
