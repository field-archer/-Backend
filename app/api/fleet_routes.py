from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.schemas.fleet import FleetTelemetryBody

router = APIRouter(prefix="/fleet", tags=["fleet"])


@router.post("/telemetry")
def report_fleet_telemetry(
    body: FleetTelemetryBody,
    _user=Depends(get_current_user),
) -> dict[str, Any]:
    """
    车队位置上报（最简版）：仅用于联调/调度，不落库。
    """
    return {"code": 20000, "message": "成功", "data": None}

