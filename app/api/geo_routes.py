from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from config.config import config
from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.models.user import User
from app.services.amap_client import place_search
from app.services.regeo_cache import (
    format_amap_regeo_api_error,
    reverse_geocode_flat_cached,
)

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/place-search")
def geo_place_search(
    q: str = Query("", max_length=128),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """代理高德地名检索；浏览器不直连图商 HTTP。"""
    key = (config.AMAP_WEB_SERVICE_KEY or "").strip()
    if not key:
        raise ApiError(50002, "图商服务未配置（amap_web_service_key）", http_status=500)

    query = (q or "").strip()
    if not query:
        raise ApiError(40000, "关键词不能为空")

    jscode = (config.AMAP_SECURITY_JSCODE or "").strip()
    items = place_search(
        key,
        query,
        jscode=jscode,
        city=config.AMAP_DEFAULT_CITY or "",
    )
    return {"code": 20000, "message": "成功", "data": items}


@router.get("/reverse-geocode")
def geo_reverse_geocode(
    longitude: float = Query(..., ge=-180.0, le=180.0),
    latitude: float = Query(..., ge=-90.0, le=90.0),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """代理高德逆地理；返回区县级全称（district / region 同义）。"""
    key = (config.AMAP_WEB_SERVICE_KEY or "").strip()
    if not key:
        raise ApiError(50002, "图商服务未配置（amap_web_service_key）", http_status=500)

    jscode = (config.AMAP_SECURITY_JSCODE or "").strip()
    outcome, flat, raw = reverse_geocode_flat_cached(
        key, longitude, latitude, jscode=jscode
    )
    if outcome == "rate_limited":
        raise ApiError(
            50002,
            "逆地理请求过于频繁（服务端限流），请稍后再试；批量补全区县请降低并发或联系运维调大 amap_regeo_max_per_minute。",
            http_status=200,
        )
    if outcome == "amap_error":
        raise ApiError(
            50002,
            format_amap_regeo_api_error(raw or {}),
            http_status=200,
        )
    if outcome == "no_district":
        raise ApiError(
            50002,
            "逆地理成功但未能解析区县展示字段（请反馈高德原始 regeocode 结构）",
            http_status=200,
        )
    if flat is None or not flat.get("district"):
        raise ApiError(
            50002,
            "逆地理成功但未能解析区县展示字段（请反馈高德原始 regeocode 结构）",
            http_status=200,
        )
    return {"code": 20000, "message": "成功", "data": flat}


@router.get("/map-config")
def geo_map_config(_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """
    登录后获取浏览器高德 JSAPI 初始化所需参数（避免把 Key 写进前端仓库）。
    前端用法：将 security_js_code 赋给 window._AMapSecurityConfig.securityJsCode，
    jsapi_key 传给 AMapLoader.load({ key })。
    """
    js_key = (config.AMAP_JSAPI_KEY or "").strip()
    if not js_key:
        raise ApiError(
            50002,
            "未配置 amap_jsapi_key（请在控制台创建「Web端(JS API)」类型 Key 并写入 config.yaml）",
            http_status=500,
        )
    sec = (config.AMAP_SECURITY_JSCODE or "").strip()
    return {
        "code": 20000,
        "message": "成功",
        "data": {
            "jsapi_key": js_key,
            "security_js_code": sec if sec else "",
        },
    }
