from pathlib import Path
from typing import Any

import yaml

import os

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
    UPLOAD_DIR: str = str(os.getenv("UPLOAD_DIR") or _DATA.get("upload_dir", "uploads"))
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

    DATABASE_URL: str = str(os.getenv("DATABASE_URL") or _DATA["database_url"])
    JWT_SECRET: str = str(os.getenv("JWT_SECRET") or _DATA["jwt_secret"])
    JWT_ALGORITHM: str = str(_DATA.get("jwt_algorithm", "HS256"))
    JWT_EXPIRE_SECONDS: int = int(os.getenv("JWT_EXPIRE_SECONDS") or _DATA.get("jwt_expire_seconds", 7200))

    # 高德 Web 服务（REST v3）：仅存服务端；仅用于服务端请求 restapi.amap.com（逆地理、检索等）
    AMAP_WEB_SERVICE_KEY: str = str(_DATA.get("amap_web_service_key", "") or "")
    # 高德 Web 端（JS API）Key：控制台平台类型为「Web端(JS API)」；供前端初始化地图（也可由本服务经鉴权接口下发）
    AMAP_JSAPI_KEY: str = str(_DATA.get("amap_jsapi_key", "") or "")
    # 与控制台「安全密钥 / securityJsCode」一致：① REST 请求作查询参数 jscode；② JSAPI 作 securityJsCode。可留空。
    AMAP_SECURITY_JSCODE: str = str(_DATA.get("amap_security_jscode", "") or "")
    # 地名检索 city 参数（如「北京」）；空则不限定城市
    AMAP_DEFAULT_CITY: str = str(_DATA.get("amap_default_city", "") or "")
    # 逆地理：服务端缓存 TTL（秒）；每分钟最多出站逆地理次数（0 表示不限流）
    AMAP_REGEO_CACHE_TTL_SECONDS: int = int(_DATA.get("amap_regeo_cache_ttl_seconds", 21600))
    AMAP_REGEO_MAX_PER_MINUTE: int = int(_DATA.get("amap_regeo_max_per_minute", 90))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


_env = str(_DATA.get("environment", "development")).lower()
if _env == "production":
    config = ProductionConfig()
else:
    config = DevelopmentConfig()
