"""高德开放平台 Web 服务（REST v3）客户端：逆地理、地名检索。"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
_INPUTTIPS_URL = "https://restapi.amap.com/v3/assistant/inputtips"


def _amap_query(base: dict[str, Any], key: str, jscode: str) -> dict[str, Any]:
    """Web 服务公共参数：key 必填；新 Key 常需附加 jscode（与控制台安全密钥/securityJsCode 一致）。"""
    q: dict[str, Any] = {**base, "key": key.strip()}
    if jscode.strip():
        q["jscode"] = jscode.strip()
    return q


def _norm_addr_scalar(v: Any) -> str:
    """高德 addressComponent 中 city/district 等可能为 []、字符串或嵌套对象，统一成展示用短字符串。"""
    if v is None:
        return ""
    if isinstance(v, dict):
        return ""
    if isinstance(v, list):
        for x in v:
            t = _norm_addr_scalar(x)
            if t:
                return t
        return ""
    s = str(v).strip()
    if not s or s in ("[]", "{}", "None", "null"):
        return ""
    return s


def _parse_location(loc: str | None) -> tuple[float, float] | None:
    if not loc or "," not in loc:
        return None
    try:
        a, b = loc.split(",", 1)
        return float(a), float(b)
    except ValueError:
        return None


def _build_district_full_name(comp: dict[str, Any]) -> str | None:
    """从 addressComponent 拼省+市+区/县（直辖市常见：省 + 区）。"""
    province = _norm_addr_scalar(comp.get("province"))
    city = _norm_addr_scalar(comp.get("city"))
    district = _norm_addr_scalar(comp.get("district"))
    if district:
        parts: list[str] = []
        if province:
            parts.append(province)
        if city and city != province:
            parts.append(city)
        parts.append(district)
        return "".join(parts) or None
    township = _norm_addr_scalar(comp.get("township"))
    if province and township:
        parts2: list[str] = [province]
        if city and city != province:
            parts2.append(city)
        parts2.append(township)
        return "".join(parts2) or None
    return None


def _regeo_empty_flat() -> dict[str, Any]:
    return {
        "district": None,
        "region": None,
        "county": None,
        "district_name": None,
        "area": None,
        "adname": None,
        "formatted_address": None,
        "address": None,
        "full_address": None,
    }


def amap_regeo_request(
    key: str,
    longitude: float,
    latitude: float,
    *,
    jscode: str = "",
    timeout: float = 8.0,
) -> dict[str, Any]:
    """请求高德逆地理接口，返回完整 JSON（含 status/info/infocode）。"""
    if not key.strip():
        return {"status": "0", "info": "MISSING_KEY", "infocode": ""}
    params = _amap_query(
        {
            "location": f"{longitude:.6f},{latitude:.6f}",
            "extensions": "all",
            "radius": "1000",
        },
        key,
        jscode,
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(_REGEO_URL, params=params)
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("amap regeo request failed: %s", e)
        return {"status": "0", "info": str(e), "infocode": ""}


def amap_regeo_response_to_flat(data: dict[str, Any]) -> dict[str, Any]:
    """
    将高德逆地理完整响应展平为《后端自检》字段。
    若 status!=1 或无法解析，返回各字段为 None 的空壳。
    """
    empty = _regeo_empty_flat()
    if str(data.get("status")) != "1":
        logger.warning(
            "amap regeo business error: info=%s infocode=%s",
            data.get("info"),
            data.get("infocode"),
        )
        return empty

    regeo = data.get("regeocode")
    if not isinstance(regeo, dict):
        return empty

    comp = regeo.get("addressComponent")
    if not isinstance(comp, dict):
        comp = {}

    fa = str(regeo.get("formatted_address") or "").strip() or None
    built = _build_district_full_name(comp)
    district_only = _norm_addr_scalar(comp.get("district")) or None

    primary = built or fa
    if primary:
        primary = primary.strip()
    if not primary:
        return empty

    # 存库与列表展示：区县级名称控制在 64 字以内（与 fire_markers.region 一致）
    primary_64 = primary[:64] if len(primary) > 64 else primary
    fa_short = fa[:120] if fa else None
    dn = district_only[:64] if district_only and len(district_only) > 64 else district_only

    return {
        "district": primary_64,
        "region": primary_64,
        "county": primary_64,
        "district_name": dn or primary_64,
        "area": primary_64,
        "adname": dn,
        "formatted_address": fa_short or primary_64,
        "address": fa_short or primary_64,
        "full_address": fa or primary_64,
    }


def reverse_geocode_flat(
    key: str,
    longitude: float,
    latitude: float,
    *,
    jscode: str = "",
    timeout: float = 8.0,
) -> dict[str, Any]:
    """
    调用高德逆地理并展平为前端《后端自检》可消费的字段。
    经进程内缓存与限流（见 app.services.regeo_cache）。
    返回键：district, region, county, district_name, area, adname,
           formatted_address, address, full_address（均为 str 或 None）。
    """
    if not key.strip():
        return _regeo_empty_flat()
    from app.services.regeo_cache import reverse_geocode_flat_cached

    out, flat, _raw = reverse_geocode_flat_cached(
        key, longitude, latitude, jscode=jscode, timeout=timeout
    )
    if flat is not None:
        return flat
    return _regeo_empty_flat()


def reverse_geocode_district(
    key: str,
    longitude: float,
    latitude: float,
    *,
    jscode: str = "",
    timeout: float = 8.0,
) -> str | None:
    """逆地理解析为区县级行政区划名称（供写库）；失败返回 None。"""
    flat = reverse_geocode_flat(
        key, longitude, latitude, jscode=jscode, timeout=timeout
    )
    return flat.get("district")


def _normalize_poi(poi: dict[str, Any]) -> dict[str, Any] | None:
    loc = _parse_location(poi.get("location"))
    if loc is None:
        return None
    lng, lat = loc
    pid = str(poi.get("id") or poi.get("poi_id") or "")
    name = str(poi.get("name") or "").strip()
    if not name:
        return None
    pname = str(poi.get("pname") or "")
    cityname = str(poi.get("cityname") or "")
    adname = str(poi.get("adname") or "")
    addr = str(poi.get("address") or "").strip()
    parts = [p for p in (pname, cityname, adname, addr) if p]
    address = "".join(parts) if parts else addr
    return {
        "id": pid or f"{lng:.6f},{lat:.6f}",
        "name": name,
        "address": address or name,
        "location": [lng, lat],
    }


def _normalize_tip(tip: dict[str, Any]) -> dict[str, Any] | None:
    loc = _parse_location(tip.get("location"))
    if loc is None:
        return None
    lng, lat = loc
    tid = str(tip.get("id") or "")
    name = str(tip.get("name") or "").strip()
    if not name:
        return None
    district = str(tip.get("district") or "")
    addr = str(tip.get("address") or "").strip()
    address = (district + addr) if (district or addr) else name
    return {
        "id": tid or f"{lng:.6f},{lat:.6f}",
        "name": name,
        "address": address,
        "location": [lng, lat],
    }


def place_search(
    key: str,
    query: str,
    *,
    jscode: str = "",
    city: str = "",
    timeout: float = 8.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """关键字地名搜索：先 place/text，无结果再 inputtips；返回与前端约定的数组结构。"""
    if not key.strip():
        return []
    q = query.strip()
    if not q:
        return []

    out: list[dict[str, Any]] = []
    seen: set[tuple[float, float, str]] = set()

    def _add(item: dict[str, Any]) -> None:
        loc = item.get("location")
        if not isinstance(loc, list) or len(loc) != 2:
            return
        key_t = (round(float(loc[0]), 5), round(float(loc[1]), 5), item.get("name", ""))
        if key_t in seen:
            return
        seen.add(key_t)
        out.append(item)

    params_text = _amap_query(
        {
            "keywords": q,
            "offset": str(min(limit, 25)),
            "page": "1",
        },
        key,
        jscode,
    )
    if city.strip():
        params_text["city"] = city.strip()

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(_PLACE_TEXT_URL, params=params_text)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("amap place/text failed: %s", e)
        data = {}

    if str(data.get("status")) == "1":
        pois = data.get("pois") or []
        if isinstance(pois, list):
            for poi in pois:
                if not isinstance(poi, dict):
                    continue
                norm = _normalize_poi(poi)
                if norm:
                    _add(norm)
                if len(out) >= limit:
                    return out[:limit]

    params_tips = _amap_query({"keywords": q}, key, jscode)
    if city.strip():
        params_tips["city"] = city.strip()

    try:
        with httpx.Client(timeout=timeout) as client:
            r2 = client.get(_INPUTTIPS_URL, params=params_tips)
            r2.raise_for_status()
            data2 = r2.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("amap inputtips failed: %s", e)
        return out[:limit]

    if str(data2.get("status")) == "1":
        tips = data2.get("tips") or []
        if isinstance(tips, list):
            for tip in tips:
                if not isinstance(tip, dict):
                    continue
                norm = _normalize_tip(tip)
                if norm:
                    _add(norm)
                if len(out) >= limit:
                    break

    return out[:limit]
