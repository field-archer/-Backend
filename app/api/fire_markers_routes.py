from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.database import get_db
from app.models.fire_marker import FireMarker
from app.models.user import User
from app.schemas.fire_marker import (
    FireMarkerCreate,
    FireMarkerListItem,
    FireMarkerOut,
    FireMarkerPageData,
    FireMarkerPatchBody,
)

router = APIRouter(prefix="/fire-markers", tags=["fire-markers"])


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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
    )
    db.add(marker)
    db.commit()
    db.refresh(marker)
    data = FireMarkerOut.model_validate(marker)
    return {"code": 20000, "message": "成功", "data": data.model_dump()}


@router.get("")
def list_markers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
    if body.note is not None:
        marker.note = body.note
    if body.fire_count is not None:
        marker.fire_count = body.fire_count
    db.commit()
    db.refresh(marker)
    data = FireMarkerOut.model_validate(marker)
    return {"code": 20000, "message": "成功", "data": data.model_dump()}
