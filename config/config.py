class Config:
    API_V1_STR = "/api"
    PROJECT_NAME = "ForestFire Backend"
    VERSION = "1.0.0"
    UPLOAD_DIR = "uploads"
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "mp4", "avi", "mov"}

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

config = DevelopmentConfig()