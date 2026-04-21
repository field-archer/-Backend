from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from config.config import config
from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.database import get_db
from app.models.fire_marker import FireMarker
from app.models.fire_marker_event import FireMarkerEvent
from app.models.user import User
from app.schemas.fire_marker import (
    FireMarkerCreate,
    FireMarkerListItem,
    FireMarkerOut,
    FireMarkerPageData,
    FireMarkerPatchBody,
    FireMarkerStatusPatchBody,
)
from app.services.amap_client import reverse_geocode_district

router = APIRouter(prefix="/fire-markers", tags=["fire-markers"])


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _apply_district_region(marker: FireMarker) -> None:
    """按经纬度逆地理写入区县级 region；未配置 Key 或失败则保持原值。"""
    key = (config.AMAP_WEB_SERVICE_KEY or "").strip()
    if not key:
        return
    jscode = (config.AMAP_SECURITY_JSCODE or "").strip()
    region = reverse_geocode_district(
        key,
        float(marker.longitude),
        float(marker.latitude),
        jscode=jscode,
    )
    if region:
        marker.region = region


@router.post("")
def create_marker(
    body: FireMarkerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    marked_at = (
        _ensure_aware(body.marked_at)
        if body.marked_at is not None
        else datetime.now(timezone.utc)
    )
    marker = FireMarker(
        user_id=user.id,
        longitude=Decimal(str(body.longitude)),
        latitude=Decimal(str(body.latitude)),
        marked_at=marked_at,
        fire_count=body.fire_count,
        source=body.source,
        note=body.note,
        status=body.status,
        level=body.level,
        cause=body.cause,
        region=None,
        reporter_username=user.username,
        reporter_user_id=user.id,
    )
    _apply_district_region(marker)
    db.add(marker)
    db.flush()
    db.refresh(marker)

    # 自检 B.2：创建即写一条台账，便于 GET /api/fire-ledger 立刻出现
    ledger_region = marker.region or "未知"
    db.add(
        FireMarkerEvent(
            marker_id=marker.id,
            region=ledger_region,
            status=marker.status,
            level=marker.level,
            reporter_username=user.username,
            event_time=marker.updated_at,
        )
    )
    db.commit()
    db.refresh(marker)
    data = FireMarkerOut.model_validate(marker)
    return {"code": 20000, "message": "成功", "data": data.model_dump()}


@router.get("")
def list_markers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
) -> dict:
    conditions = [FireMarker.user_id == user.id]
    if from_ is not None:
        conditions.append(FireMarker.marked_at >= _ensure_aware(from_))
    if to is not None:
        conditions.append(FireMarker.marked_at <= _ensure_aware(to))
    where_clause = and_(*conditions)

    total = db.execute(
        select(func.count()).select_from(FireMarker).where(where_clause)
    ).scalar_one()

    rows = db.scalars(
        select(FireMarker)
        .where(where_clause)
        .order_by(FireMarker.marked_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [FireMarkerListItem.model_validate(r) for r in rows]
    page_data = FireMarkerPageData(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
    return {"code": 20000, "message": "成功", "data": page_data.model_dump()}


@router.delete("/{marker_id}")
def delete_marker(
    marker_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    marker = db.get(FireMarker, marker_id)
    if marker is None or marker.user_id != user.id:
        raise ApiError(40400, "资源不存在")
    db.delete(marker)
    db.commit()
    return {"code": 20000, "message": "成功", "data": None}


@router.patch("/{marker_id}")
def patch_marker(
    marker_id: int,
    body: FireMarkerPatchBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    marker = db.get(FireMarker, marker_id)
    if marker is None or marker.user_id != user.id:
        raise ApiError(40400, "资源不存在")

    wrote_event = False
    coord_changed = False
    if body.longitude is not None or body.latitude is not None:
        if body.longitude is None or body.latitude is None:
            raise ApiError(40000, "更新坐标时需同时传入 longitude 与 latitude")
        marker.longitude = Decimal(str(body.longitude))
        marker.latitude = Decimal(str(body.latitude))
        coord_changed = True

    if body.note is not None:
        marker.note = body.note
    if body.fire_count is not None:
        marker.fire_count = body.fire_count

    if body.status is not None and body.status != marker.status:
        marker.status = body.status
        wrote_event = True
    if body.level is not None and body.level != marker.level:
        marker.level = body.level
        wrote_event = True
    if body.cause is not None and body.cause != marker.cause:
        marker.cause = body.cause
        wrote_event = True

    if wrote_event:
        marker.reporter_username = user.username
        marker.reporter_user_id = user.id

    if coord_changed or wrote_event:
        _apply_district_region(marker)

    db.flush()
    db.refresh(marker)

    if wrote_event:
        event = FireMarkerEvent(
            marker_id=marker.id,
            region=marker.region or "未知",
            status=marker.status,
            level=marker.level,
            reporter_username=user.username,
            event_time=marker.updated_at,
        )
        db.add(event)

    db.commit()
    data = FireMarkerOut.model_validate(marker)
    return {"code": 20000, "message": "成功", "data": data.model_dump()}


@router.patch("/{marker_id}/status")
def patch_marker_status(
    marker_id: int,
    body: FireMarkerStatusPatchBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    marker = db.get(FireMarker, marker_id)
    if marker is None or marker.user_id != user.id:
        raise ApiError(40400, "资源不存在")
    marker.status = body.status
    marker.reporter_username = user.username
    marker.reporter_user_id = user.id
    _apply_district_region(marker)
    db.flush()
    db.refresh(marker)

    event = FireMarkerEvent(
        marker_id=marker.id,
        region=marker.region or "未知",
        status=marker.status,
        level=marker.level,
        reporter_username=user.username,
        event_time=marker.updated_at,
    )
    db.add(event)
    db.commit()

    data = FireMarkerOut.model_validate(marker)
    return {"code": 20000, "message": "成功", "data": data.model_dump()}
