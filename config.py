import os

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    ENVIRONMENT = os.environ.get('HMS_ENV', 'development').lower()
    AUTO_INIT_DB = ENVIRONMENT != 'production'
    SEED_DEMO_DATA = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 
        f"sqlite:///{os.path.join(BASE_DIR, 'hms.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEMO_LOGIN_ENABLED = os.environ.get('HMS_ENABLE_DEMO_LOGIN', '').lower() == 'true'
    
    # CSRF Protection Settings
    WTF_CSRF_ENABLED = os.environ.get('WTF_CSRF_ENABLED', 'true').lower() == 'true'
    WTF_CSRF_TIME_LIMIT = None  # None matches session lifespan for clinical workflows

    # Upload settings
    PRIVATE_UPLOAD_FOLDER = os.path.join(BASE_DIR, 'instance', 'private')
    UPLOAD_FOLDER = os.path.join(PRIVATE_UPLOAD_FOLDER, 'photos')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    CONSULTATION_FEE = 500.0
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = ENVIRONMENT == 'production'
    
    # Facility information for printables & headers
    FACILITY_NAME = "Apex Regional Medical Center"
    FACILITY_CODE = "HSP-2026"
    FACILITY_ADDRESS = "Hospital Road, Medical District, P.O. Box 40100"
    FACILITY_PHONE = "+254 (0) 20 555 0190 / +254 700 000 100"
    FACILITY_EMAIL = "reception@apexmedical.org"
    FACILITY_TAX_PIN = "P051298471Z"
