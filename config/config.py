from pathlib import Path
from typing import Any

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent
_CONFIG_FILE = _CONFIG_DIR / "config.yaml"


def _load_yaml() -> dict[str, Any]:
    if not _CONFIG_FILE.is_file():
        raise FileNotFoundError(
            f"缺少配置文件: {_CONFIG_FILE}（请在该路径创建 config.yaml）"
        )
    with _CONFIG_FILE.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("config.yaml 根节点必须为映射表（键值对）")
    return data


_DATA = _load_yaml()


class Config:
    API_V1_STR: str = str(_DATA.get("api_v1_str", "/api"))
    PROJECT_NAME: str = str(_DATA.get("project_name", "ForestFire Backend"))
    VERSION: str = str(_DATA.get("version", "1.0.0"))
    UPLOAD_DIR: str = str(_DATA.get("upload_dir", "uploads"))
    raw_exts = _DATA.get("allowed_extensions")
    if not isinstance(raw_exts, list) or not raw_exts:
        ALLOWED_EXTENSIONS: set[str] = {
            "jpg",
            "jpeg",
            "png",
            "gif",
            "mp4",
            "avi",
            "mov",
        }
    else:
        ALLOWED_EXTENSIONS = {str(x).lower().lstrip(".") for x in raw_exts}

    DATABASE_URL: str = str(_DATA["database_url"])
    JWT_SECRET: str = str(_DATA["jwt_secret"])
    JWT_ALGORITHM: str = str(_DATA.get("jwt_algorithm", "HS256"))
    JWT_EXPIRE_SECONDS: int = int(_DATA.get("jwt_expire_seconds", 7200))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


_env = str(_DATA.get("environment", "development")).lower()
if _env == "production":
    config = ProductionConfig()
else:
    config = DevelopmentConfig()
