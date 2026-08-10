import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

# Repo root (backend/app/.. -> backend/.. -> repo root); uploads live outside the package
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


class Config:
    """Base configuration"""
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://localhost/partsbin')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_SECURE = os.getenv('FLASK_ENV') == 'production'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # File upload configuration
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
    MAX_IMAGE_SIZE = int(os.getenv('MAX_IMAGE_SIZE', 5 * 1024 * 1024))  # 5MB
    MAX_PDF_SIZE = int(os.getenv('MAX_PDF_SIZE', 25 * 1024 * 1024))  # 25MB
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 50 * 1024 * 1024))  # 50MB (project files)
    MAX_MODEL_SIZE = int(os.getenv('MAX_MODEL_SIZE', 64 * 1024 * 1024))  # 64MB (3D print models)
    ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
    ALLOWED_PDF_TYPES = {'application/pdf'}
    # 3D models are validated by EXTENSION, not magic bytes: every mesh format
    # sniffs as application/octet-stream (binary STL), text/plain (ASCII STL,
    # OBJ, STEP, gcode) or application/zip (3MF), so a MIME whitelist would
    # either reject everything or wave through any binary blob.
    ALLOWED_MODEL_EXTENSIONS = {
        '.stl', '.3mf', '.obj', '.step', '.stp', '.scad', '.gcode', '.bgcode', '.f3d',
    }

    # TOTP configuration
    TOTP_ISSUER_NAME = os.getenv('TOTP_ISSUER_NAME', 'PartsBin')
    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

    # CORS configuration
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',')


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SQLALCHEMY_ECHO = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
