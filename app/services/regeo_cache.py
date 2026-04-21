"""逆地理：进程内 TTL 缓存 + 每分钟出站限流，降低高德 QPS/日配额触发（见 docs/前后端对接/后端须知 第 2 条）。"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Literal

from config.config import config
from app.services.amap_client import amap_regeo_request, amap_regeo_response_to_flat

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_calls: deque[float] = deque()

RegeoOutcome = Literal[
    "cached",
    "ok",
    "rate_limited",
    "amap_error",
    "no_district",
]


def _cache_key(longitude: float, latitude: float) -> str:
    return f"{longitude:.5f},{latitude:.5f}"


def _evict_old_calls(now: float) -> None:
    while _calls and now - _calls[0] > 60.0:
        _calls.popleft()


def _rate_limit_allows() -> bool:
    cap = int(config.AMAP_REGEO_MAX_PER_MINUTE)
    if cap <= 0:
        return True
    now = time.monotonic()
    with _lock:
        _evict_old_calls(now)
        return len(_calls) < cap


def _record_outbound_call() -> None:
    cap = int(config.AMAP_REGEO_MAX_PER_MINUTE)
    if cap <= 0:
        return
    now = time.monotonic()
    with _lock:
        _evict_old_calls(now)
        _calls.append(now)


def _get_cached_flat(longitude: float, latitude: float) -> dict[str, Any] | None:
    now = time.monotonic()
    k = _cache_key(longitude, latitude)
    with _lock:
        ent = _cache.get(k)
        if ent and ent[0] > now and ent[1].get("district"):
            return ent[1]
    return None


def _store_flat(longitude: float, latitude: float, flat: dict[str, Any]) -> None:
    if not flat.get("district"):
        return
    ttl = max(60, int(config.AMAP_REGEO_CACHE_TTL_SECONDS))
    k = _cache_key(longitude, latitude)
    exp = time.monotonic() + float(ttl)
    with _lock:
        _cache[k] = (exp, flat)
        if len(_cache) > 8000:
            _prune_cache_unlocked()


def _prune_cache_unlocked() -> None:
    now = time.monotonic()
    dead = [k for k, (t, _) in _cache.items() if t <= now]
    for k in dead[:4000]:
        _cache.pop(k, None)


def _is_quota_error(raw: dict[str, Any]) -> bool:
    code = str(raw.get("infocode") or "")
    info = str(raw.get("info") or "")
    if code == "10021":
        return True
    u = info.upper()
    return "CUQPS" in u or ("QPS" in u and "EXCEED" in u)


def format_amap_regeo_api_error(raw: dict[str, Any]) -> str:
    """供 HTTP 层返回可读 message（含配额/QPS 说明）。"""
    if _is_quota_error(raw):
        return (
            "高德逆地理日配额或并发 QPS 超限（如 infocode=10021、CUQPS_HAS_EXCEEDED_THE_LIMIT）；"
            "请在控制台提额或购买配额，或稍后重试。服务端已对逆地理做缓存与限流以降低触发频率。"
        )
    info = raw.get("info") or "未知错误"
    code = raw.get("infocode") or ""
    return f"高德逆地理失败: {info}" + (f" (infocode={code})" if code else "")


def reverse_geocode_flat_cached(
    key: str,
    longitude: float,
    latitude: float,
    *,
    jscode: str = "",
    timeout: float = 8.0,
) -> tuple[RegeoOutcome, dict[str, Any] | None, dict[str, Any] | None]:
    """
    带缓存与限流的逆地理展平结果。
    返回 (outcome, flat, raw)：成功时 raw 可为 None；amap_error 时 raw 为高德原始 JSON。
    """
    hit = _get_cached_flat(longitude, latitude)
    if hit is not None:
        return "cached", hit, None

    if not _rate_limit_allows():
        return "rate_limited", None, None

    _record_outbound_call()
    raw = amap_regeo_request(
        key, longitude, latitude, jscode=jscode, timeout=timeout
    )
    if str(raw.get("status")) != "1":
        return "amap_error", None, raw

    flat = amap_regeo_response_to_flat(raw)
    if not flat.get("district"):
        return "no_district", flat, raw

    _store_flat(longitude, latitude, flat)
    return "ok", flat, raw


def district_for_marker_write(
    key: str,
    longitude: float,
    latitude: float,
    *,
    jscode: str = "",
    timeout: float = 8.0,
) -> str | None:
    """写库用：成功返回区县字符串；限流/失败/无区县返回 None（保持原 region）。"""
    out, flat, _raw = reverse_geocode_flat_cached(
        key, longitude, latitude, jscode=jscode, timeout=timeout
    )
    if out in ("cached", "ok") and flat:
        d = flat.get("district")
        return str(d) if d else None
    return None
